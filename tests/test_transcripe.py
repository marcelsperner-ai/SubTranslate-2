import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from app import create_app
from app.db import (
    archive_translation, get_all_translations, get_db_connection,
    get_translation_by_id, init_db, save_default_settings,
)
from app.services.transcripe_service import (
    import_transcript, import_video, metadata_context, read_manifest, resolve_source,
)


SRT = '1\n00:00:02,600 --> 00:00:05,200\nHallo Welt.\n'
WORDS = [{'word': 'Hallo Welt.', 'start_sec': 2.6, 'end_sec': 5.0}]


class TranscripeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        patcher = patch('app.db.DB_PATH', str(self.root / 'db.sqlite'))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = create_app()
        self.app.instance_path = str(self.root / 'instance')
        self.app.config['UPLOADS_DIR'] = str(self.root / 'uploads')
        self.uploads = Path(self.app.config['UPLOADS_DIR'])
        self.uploads.mkdir()
        self.inbox = self.root / 'inbox'
        self.job = self.inbox / 'Auftrag'
        self.job.mkdir(parents=True)
        self.integration = self.app.extensions['transcripe']
        self.addCleanup(self.integration.stop)
        self.client = self.app.test_client()

    def package(self, *, audio=False, metadata=True, export_id=None):
        files = {
            'srt': ('probe.srt', SRT.encode()),
            'words': ('probe.words.json', json.dumps(WORDS).encode()),
        }
        if metadata:
            files['metadata'] = ('probe.json', json.dumps({
                'title': 'Videotitel', 'channel_name': 'Beispielkanal',
                'description': 'Beschreibung als Kontext.',
            }).encode())
        if audio:
            files['audio'] = ('.media\\probe.wav', b'example-audio')
        manifest = {'version': 1, 'export_id': export_id or str(uuid4()),
                    **dict.fromkeys(('srt', 'words', 'metadata', 'words_original', 'words_review', 'audio')),
                    'sha256': {}}
        for field, (name, content) in files.items():
            path = self.job / name.replace('\\', '/')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            manifest[field] = name
            manifest['sha256'][field] = hashlib.sha256(content).hexdigest()
        marker = self.job / 'probe.ready.json'
        marker.write_text(json.dumps(manifest))
        return marker, manifest

    def video_marker(self, export_id):
        content = b'example-video'
        (self.job / 'probe.mkv').write_bytes(content)
        marker = self.job / 'probe.media.json'
        marker.write_text(json.dumps({
            'version': 1, 'export_id': export_id, 'video': 'probe.mkv',
            'sha256': {'video': hashlib.sha256(content).hexdigest()},
        }))
        return marker

    def enable(self):
        save_default_settings('transcripe', {'enabled': True, 'inbox_dir': str(self.inbox)})

    def package_with_source(self, source='youtube_manual', precision='segment', language='de-DE'):
        marker, manifest = self.package()
        metadata = {
            'title': 'Gleicher Videotitel', 'source_id': 'TESTVIDEO01',
            'subtitle_source': source, 'language': language, 'timing_precision': precision,
        }
        content = json.dumps(metadata).encode('utf-8')
        (self.job / manifest['metadata']).write_bytes(content)
        manifest['sha256']['metadata'] = hashlib.sha256(content).hexdigest()
        marker.write_text(json.dumps(manifest), encoding='utf-8')
        return marker, manifest, metadata

    def test_manual_youtube_segment_metadata_persists_without_changing_srt(self):
        marker, manifest, metadata = self.package_with_source()
        project_id = import_transcript(marker, self.uploads)
        project = get_translation_by_id(project_id)
        self.assertEqual(project['status'], 'pausiert')
        self.assertFalse(project['translation_started'])
        self.assertEqual((self.uploads / project['original_filename']).read_bytes(), SRT.encode())
        info = self.client.get(f'/api/transcripe/project/{project_id}').get_json()
        self.assertEqual(info['metadata'], metadata)
        words = json.loads((self.uploads / info['assets']['words']).read_text())
        self.assertEqual(words, WORDS)
        self.assertIn(' ', words[0]['word'])
        new_app = create_app()
        self.addCleanup(new_app.extensions['transcripe'].stop)
        self.assertEqual(new_app.test_client().get(
            f'/api/project/{project_id}').get_json()['import_metadata'], metadata)
        archive_translation(project_id)
        listed = self.client.get('/api/projects').get_json()[0]
        self.assertTrue(listed['archived'])
        self.assertEqual(listed['import_metadata'], metadata)
        (self.job / manifest['metadata']).write_bytes(b'overwritten metadata')
        self.assertEqual(import_transcript(marker, self.uploads), project_id)
        self.assertEqual(self.client.get(
            f'/api/transcripe/project/{project_id}').get_json()['metadata'], metadata)

    def test_same_video_has_independent_source_projects_and_video_copies(self):
        marker, first, first_metadata = self.package_with_source()
        first_id = import_transcript(marker, self.uploads)
        video_marker = self.video_marker(first['export_id'])
        self.assertEqual(import_video(video_marker, self.uploads), first_id)
        marker, second, second_metadata = self.package_with_source(
            source='transcription', precision='word_or_segment')
        second_video = self.video_marker(second['export_id'])
        self.assertIsNone(import_video(second_video, self.uploads))
        second_id = import_transcript(marker, self.uploads)
        self.assertNotEqual(first_id, second_id)
        self.assertEqual(import_video(second_video, self.uploads), second_id)
        self.assertEqual(import_video(second_video, self.uploads), second_id)
        self.assertEqual(len(get_all_translations()), 2)
        first_info = self.client.get(f'/api/transcripe/project/{first_id}').get_json()
        second_info = self.client.get(f'/api/transcripe/project/{second_id}').get_json()
        self.assertEqual(first_info['metadata'], first_metadata)
        self.assertEqual(second_info['metadata'], second_metadata)
        self.assertNotEqual(first_info['assets']['video'], second_info['assets']['video'])
        for info in (first_info, second_info):
            self.assertEqual((self.uploads / info['assets']['video']).read_bytes(), b'example-video')
        projects = self.client.get('/api/projects').get_json()
        self.assertEqual({p['import_metadata']['subtitle_source'] for p in projects},
                         {'youtube_manual', 'transcription'})

    def test_legacy_optional_and_unknown_source_metadata_are_supported(self):
        marker, _ = self.package(metadata=False)
        project_id = import_transcript(marker, self.uploads)
        self.assertEqual(self.client.get(
            f'/api/project/{project_id}').get_json()['import_metadata'], {})
        marker, _, metadata = self.package_with_source(source='future_source', precision=None, language=None)
        project_id = import_transcript(marker, self.uploads)
        self.assertEqual(self.client.get(
            f'/api/project/{project_id}').get_json()['import_metadata'], metadata)

    def test_invalid_source_metadata_rejects_import_without_partial_project(self):
        for field in ('source_id', 'subtitle_source', 'language', 'timing_precision'):
            marker, manifest, metadata = self.package_with_source()
            metadata[field] = ['invalid']
            content = json.dumps(metadata).encode('utf-8')
            (self.job / manifest['metadata']).write_bytes(content)
            manifest['sha256']['metadata'] = hashlib.sha256(content).hexdigest()
            marker.write_text(json.dumps(manifest))
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                import_transcript(marker, self.uploads)
            self.assertEqual(get_all_translations(), [])
            self.assertEqual(list(self.uploads.iterdir()), [])

    def test_import_metadata_migration_preserves_legacy_mapping(self):
        marker, manifest = self.package(metadata=False)
        project_id = import_transcript(marker, self.uploads)
        connection = get_db_connection()
        try:
            connection.execute('ALTER TABLE transcripe_imports DROP COLUMN metadata_json')
            connection.commit()
        finally:
            connection.close()
        init_db()
        init_db()
        info = self.client.get(f'/api/transcripe/project/{project_id}').get_json()
        self.assertEqual(info['metadata'], {})
        self.assertEqual(info['export_id'], manifest['export_id'])
        self.assertEqual(import_transcript(marker, self.uploads), project_id)

    def test_import_uses_defaults_context_and_verified_independent_copies(self):
        marker, manifest = self.package(audio=True)
        save_default_settings('srt', {'batch_size': 17, 'sync_offset': 250})
        t_id = import_transcript(marker, self.uploads)
        project = get_translation_by_id(t_id)
        self.assertEqual(project['status'], 'pausiert')
        self.assertFalse(project['translation_started'])
        self.assertEqual(project['project_name'], 'Videotitel')
        self.assertEqual(project['batch_size'], 17)
        self.assertEqual(project['sync_offset'], 250)
        self.assertIn('Beispielkanal', project['episode_summary'])
        self.assertIn('Beschreibung als Kontext.', project['episode_summary'])
        prompt = self.client.get(f'/api/prompts/{t_id}').get_json()['translation_prompt']
        self.assertIn(project['episode_summary'], prompt)
        self.assertEqual((self.uploads / project['original_filename']).read_text(), SRT)
        info = self.client.get(f'/api/transcripe/project/{t_id}').get_json()
        self.assertEqual(info['source_filename'], 'probe.srt')
        self.assertEqual(info['export_id'], manifest['export_id'])
        self.assertEqual((self.uploads / info['assets']['audio']).read_bytes(), b'example-audio')
        (self.job / 'probe.srt').write_text('overwritten')
        self.assertEqual((self.uploads / project['original_filename']).read_text(), SRT)
        self.assertEqual(import_transcript(marker, self.uploads), t_id)

    def test_new_export_produces_distinct_project_and_dedup_survives_new_app(self):
        marker, first = self.package(metadata=False)
        first_id = import_transcript(marker, self.uploads)
        self.assertEqual(import_transcript(marker, self.uploads), first_id)
        marker, second = self.package(metadata=False)
        second_id = import_transcript(marker, self.uploads)
        self.assertNotEqual(first['export_id'], second['export_id'])
        self.assertNotEqual(first_id, second_id)
        self.assertEqual(len(get_all_translations()), 2)
        self.assertEqual(get_translation_by_id(second_id)['episode_summary'], '')
        new_app = create_app()
        self.addCleanup(new_app.extensions['transcripe'].stop)
        self.assertEqual(import_transcript(marker, self.uploads), second_id)

    def test_checksum_failure_is_visible_and_corrected_scan_retries(self):
        marker, _ = self.package()
        (self.job / 'probe.srt').write_text(SRT + '\nchanged')
        self.enable()
        self.integration.scan()
        status = self.integration.status()
        self.assertEqual(status['import_count'], 0)
        self.assertEqual(status['error_count'], 1)
        self.assertTrue(any('Pruefsumme' in event['message'] for event in status['events']))
        self.assertEqual(list(self.uploads.iterdir()), [])
        (self.job / 'probe.srt').write_text(SRT)
        self.integration.scan()
        self.assertEqual(self.integration.status()['import_count'], 1)
        self.assertEqual(self.integration.status()['error_count'], 0)

    def test_no_marker_means_no_import_and_internal_markers_are_ignored(self):
        marker, _ = self.package()
        internal = self.job / '.media'
        internal.mkdir()
        marker.replace(internal / marker.name)
        self.enable()
        self.integration.scan()
        self.assertEqual(get_all_translations(), [])

    def test_video_arrives_before_transcript_then_is_attached_once(self):
        export_id = str(uuid4())
        video = self.video_marker(export_id)
        self.enable()
        self.integration.scan()
        self.assertTrue(any(event['level'] == 'pending' for event in self.integration.status()['events']))
        marker, _ = self.package(export_id=export_id)
        self.integration.scan()
        project_id = get_all_translations()[0]['id']
        self.assertEqual(import_video(video, self.uploads), project_id)
        info = self.client.get(f'/api/transcripe/project/{project_id}').get_json()
        self.assertEqual((self.uploads / info['assets']['video']).read_bytes(), b'example-video')
        self.assertEqual(len(get_all_translations()), 1)
        self.integration.scan()
        self.assertEqual(self.integration.status()['error_count'], 0)

    def test_late_video_hash_failure_preserves_transcript(self):
        marker, manifest = self.package()
        project_id = import_transcript(marker, self.uploads)
        video = self.video_marker(manifest['export_id'])
        (self.job / 'probe.mkv').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            import_video(video, self.uploads)
        self.assertIsNotNone(get_translation_by_id(project_id))
        self.assertNotIn('video', self.client.get(f'/api/transcripe/project/{project_id}').get_json()['assets'])
        (self.job / 'probe.mkv').write_bytes(b'example-video')
        self.assertEqual(import_video(video, self.uploads), project_id)

    def test_rejects_path_escape_absolute_paths_and_symlinks(self):
        outside = self.root / 'outside.srt'
        outside.write_text(SRT)
        for value in ('../outside.srt', '/etc/passwd', 'C:\\outside.srt', '\\outside.srt', 'probe.srt:stream'):
            with self.subTest(path=value), self.assertRaises((ValueError, OSError)):
                resolve_source(self.job, value)
        (self.job / 'linked.srt').symlink_to(outside)
        with self.assertRaises(ValueError):
            resolve_source(self.job, 'linked.srt')

    def test_manifest_requires_exact_hash_keys_and_uuid(self):
        marker, manifest = self.package()
        for changes in ({'version': True}, {'export_id': 'bad'}, {'words': None},
                        {'sha256': {}}, {'sha256': {**manifest['sha256'], 'audio': 'a' * 64}}):
            marker.write_text(json.dumps({**manifest, **changes}))
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                read_manifest(marker)

    def test_invalid_words_rejected_before_project_creation(self):
        marker, manifest = self.package()
        path = self.job / manifest['words']
        content = json.dumps([{'word': 'Text', 'start_sec': True, 'end_sec': 4}]).encode()
        path.write_bytes(content)
        manifest['sha256']['words'] = hashlib.sha256(content).hexdigest()
        marker.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            import_transcript(marker, self.uploads)
        self.assertEqual(get_all_translations(), [])

    def test_metadata_nulls_do_not_invent_context(self):
        path = self.job / 'metadata.json'
        path.write_text(json.dumps({'title': None, 'channel_name': None, 'description': None}))
        self.assertEqual(metadata_context(path), ('', ''))

    def test_manifest_replaced_while_copying_rejects_snapshot(self):
        marker, manifest = self.package()
        from app.services.transcripe_service import copy_verified

        def replace_after_copy(source, destination, expected_hash):
            copy_verified(source, destination, expected_hash)
            if source.name.endswith('.words.json'):
                marker.write_text(json.dumps({**manifest, 'export_id': str(uuid4())}))

        with patch('app.services.transcripe_service.copy_verified', side_effect=replace_after_copy):
            with self.assertRaisesRegex(ValueError, 'ersetzt'):
                import_transcript(marker, self.uploads)
        self.assertEqual(get_all_translations(), [])
        self.assertEqual(list(self.uploads.iterdir()), [])

    def test_current_review_files_are_validated_but_stale_unlisted_files_are_ignored(self):
        marker, manifest = self.package()
        (self.job / 'probe.words.review.json').write_text('stale invalid json')
        first_id = import_transcript(marker, self.uploads)
        first_info = self.client.get(f'/api/transcripe/project/{first_id}').get_json()
        self.assertNotIn('words_review', first_info['assets'])
        marker, manifest = self.package()
        review = [{
            'first_word_id': 1, 'last_word_id': 1, 'original': 'Hallo',
            'replacement': 'Guten Tag', 'reason': 'Test', 'category': 'recognition',
            'confidence': 'medium', 'audio_required': True, 'decision': 'Übernehmen',
            'approved_replacement': None, 'full_subtitle_edit': 'Guten Tag Welt.',
        }]
        for field, data in (('words_original', WORDS), ('words_review', review)):
            name = f'probe.{field}.json'
            content = json.dumps(data).encode()
            (self.job / name).write_bytes(content)
            manifest[field] = name
            manifest['sha256'][field] = hashlib.sha256(content).hexdigest()
        marker.write_text(json.dumps(manifest))
        second_id = import_transcript(marker, self.uploads)
        second_info = self.client.get(f'/api/transcripe/project/{second_id}').get_json()
        self.assertIn('words_review', second_info['assets'])
        self.assertIn('words_original', second_info['assets'])

    def test_invalid_srt_is_not_imported(self):
        marker, manifest = self.package()
        content = b'not a subtitle\n'
        (self.job / manifest['srt']).write_bytes(content)
        manifest['sha256']['srt'] = hashlib.sha256(content).hexdigest()
        marker.write_text(json.dumps(manifest))
        self.enable()
        self.integration.scan()
        self.assertEqual(self.integration.status()['import_count'], 0)
        self.assertEqual(self.integration.status()['error_count'], 1)

    def test_background_watcher_imports_existing_marker(self):
        self.package()
        self.enable()
        imported = threading.Event()
        original_scan = self.integration.scan

        def scan_and_signal():
            original_scan()
            imported.set()

        with patch.object(self.integration, 'scan', side_effect=scan_and_signal):
            self.integration.start()
            self.assertTrue(imported.wait(timeout=10))
            self.integration.stop()
        self.assertEqual(len(get_all_translations()), 1)

    def test_rendered_settings_tab_is_not_nested_in_another_form(self):
        from html.parser import HTMLParser

        class Parser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.forms = []
                self.nested = False
                self.transcripe_seen = False

            def handle_starttag(self, tag, attrs):
                if tag == 'form':
                    self.nested |= bool(self.forms)
                    self.forms.append(dict(attrs).get('id'))
                    self.transcripe_seen |= self.forms[-1] == 'transcripeSettingsForm'

            def handle_endtag(self, tag):
                if tag == 'form' and self.forms:
                    self.forms.pop()

        html = self.client.get('/').get_data(as_text=True)
        parser = Parser()
        parser.feed(html)
        self.assertTrue(parser.transcripe_seen)
        self.assertFalse(parser.nested)
        self.assertIn('js/transcripe.js', html)

    def test_database_failure_rolls_back_project_and_files(self):
        marker, _ = self.package()
        with patch('app.services.transcripe_service.create_translation', side_effect=ValueError('test failure')):
            with self.assertRaises(ValueError):
                import_transcript(marker, self.uploads)
        self.assertEqual(get_all_translations(), [])
        self.assertEqual(list(self.uploads.glob('*.srt')), [])
        self.assertEqual(list((self.uploads / 'transcripe').iterdir()), [])
        import_transcript(marker, self.uploads)
        self.assertEqual(len(get_all_translations()), 1)

    def test_concurrent_imports_create_only_one_project(self):
        marker, _ = self.package()
        results, errors = [], []

        def run():
            try:
                results.append(import_transcript(marker, self.uploads))
            except Exception as error:
                errors.append(error)

        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(len(get_all_translations()), 1)

    def test_settings_validation_and_launch_existing_server(self):
        self.assertFalse(self.client.get('/api/transcripe/settings').get_json()['enabled'])
        bad = self.client.post('/api/transcripe/settings', json={'enabled': True, 'inbox_dir': 'relative'})
        self.assertEqual(bad.status_code, 400)
        missing = self.client.post('/api/transcripe/launch')
        with patch.object(self.integration, '_healthy', return_value=True):
            response = self.client.post('/api/transcripe/launch')
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['url'], 'http://127.0.0.1:8501/')

    def test_settings_enable_watcher_and_persist(self):
        values = {'enabled': True, 'inbox_dir': str(self.inbox), 'app_dir': '', 'python_path': ''}
        with patch.object(self.integration, 'start') as start:
            response = self.client.post('/api/transcripe/settings', json=values)
        self.assertEqual(response.status_code, 200)
        start.assert_called_once()
        self.assertEqual(self.client.get('/api/transcripe/settings').get_json(), values)
        self.assertEqual(self.client.post('/api/transcripe/scan').status_code, 200)

    def test_launcher_uses_configured_interpreter_and_waits_for_health(self):
        app_dir = self.root / 'streamlit'
        app_dir.mkdir()
        (app_dir / 'app.py').write_text('# test')
        interpreter = app_dir / 'python.exe'
        interpreter.write_bytes(b'test')
        save_default_settings('transcripe', {
            'app_dir': str(app_dir), 'python_path': str(interpreter),
        })
        process = Mock()
        process.poll.return_value = None
        with patch.object(self.integration, '_healthy', side_effect=[False, True]), \
                patch('app.services.transcripe_service.subprocess.Popen', return_value=process) as popen:
            response = self.client.post('/api/transcripe/launch')
        self.assertEqual(response.status_code, 200)
        args, kwargs = popen.call_args
        self.assertEqual(args[0][:4], [str(interpreter), '-m', 'streamlit', 'run'])
        self.assertEqual(kwargs['cwd'], app_dir)
        self.assertIn('127.0.0.1', args[0])


if __name__ == '__main__':
    unittest.main()
