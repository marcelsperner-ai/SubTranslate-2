from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from app import create_app
from app.db import acquire_translation_lock, create_translation, update_edtech_status
from app.services.media_player_service import find_vlc


class MediaPlayerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        db = patch('app.db.DB_PATH', str(self.root / 'db.sqlite'))
        db.start()
        self.addCleanup(db.stop)
        self.app = create_app()
        self.app.testing = True
        self.app.config.update(UPLOADS_DIR=str(self.root / 'uploads'), OUTPUTS_DIR=str(self.root / 'outputs'))
        self.uploads = Path(self.app.config['UPLOADS_DIR'])
        self.outputs = Path(self.app.config['OUTPUTS_DIR'])
        self.uploads.mkdir()
        self.outputs.mkdir()
        self.video = self.uploads / 'video with spaces.mp4'
        self.video.write_bytes(b'test video')
        self.srt = self.outputs / 'source_FA.srt'
        self.srt.write_text('test subtitle', encoding='utf-8')
        self.ass = self.outputs / 'source_Interaktiv.ass'
        with self.app.app_context():
            self.project_id = create_translation('source.srt', 10, 0, 'default', '')
        self.client = self.app.test_client()
        self.url = f'/api/transcripe/project/{self.project_id}/play'
        imported = patch('app.services.media_player_service.project_import_info',
                         return_value={'assets': {'video': self.video.name}})
        self.imported = imported.start()
        self.addCleanup(imported.stop)
        vlc = patch('app.services.media_player_service.find_vlc', return_value='vlc.exe')
        self.vlc = vlc.start()
        self.addCleanup(vlc.stop)
        process = Mock()
        process.wait.side_effect = subprocess.TimeoutExpired('vlc', 0.5)
        popen = patch('app.services.media_player_service.subprocess.Popen', return_value=process)
        self.popen = popen.start()
        self.addCleanup(popen.stop)

    def test_srt_fallback_and_separate_process_arguments(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('SRT', response.get_json()['message'])
        args = self.popen.call_args.args[0]
        self.assertIn(f'--sub-file={self.srt}', args)
        self.assertEqual(args[-2:], ['--', str(self.video)])
        self.assertIn('--no-one-instance', args)

    def test_ass_preferred_and_missing_ass_falls_back(self):
        self.ass.write_text('test ASS', encoding='utf-8')
        update_edtech_status(self.project_id, 1)
        response = self.client.post(self.url)
        self.assertIn('ASS', response.get_json()['message'])
        self.assertIn(f'--sub-file={self.ass}', self.popen.call_args.args[0])
        self.ass.unlink()
        self.assertIn('SRT', self.client.post(self.url).get_json()['message'])

    def test_unfinished_ass_is_not_used(self):
        self.ass.write_text('unfinished ASS', encoding='utf-8')
        self.assertIn('SRT', self.client.post(self.url).get_json()['message'])

    def test_missing_video_subtitle_or_project_does_not_launch(self):
        self.video.unlink()
        self.assertEqual(self.client.post(self.url).status_code, 400)
        self.video.write_bytes(b'video')
        self.srt.unlink()
        self.assertEqual(self.client.post(self.url).status_code, 400)
        self.assertEqual(self.client.post('/api/transcripe/project/99999/play').status_code, 400)
        self.imported.return_value = None
        self.assertEqual(self.client.post(self.url).status_code, 400)
        self.popen.assert_not_called()

    def test_external_paths_are_rejected(self):
        outside = self.root / 'outside.mp4'
        outside.write_bytes(b'outside')
        for path in ('../outside.mp4', str(outside)):
            self.imported.return_value = {'assets': {'video': path}}
            self.assertEqual(self.client.post(self.url).status_code, 400)
        self.popen.assert_not_called()

    def test_remote_and_cross_origin_launches_are_rejected(self):
        for options in (
            {'environ_overrides': {'REMOTE_ADDR': '192.168.1.2'}},
            {'headers': {'Origin': 'https://example.com'}},
            {'headers': {'Sec-Fetch-Site': 'cross-site'}},
            {'headers': {'Host': 'example.com'}},
        ):
            self.assertEqual(self.client.post(self.url, **options).status_code, 403)
        self.popen.assert_not_called()
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_same_origin_is_allowed(self):
        self.assertEqual(self.client.post(self.url, headers={'Origin': 'http://localhost'}).status_code, 200)

    def test_missing_vlc_and_process_errors_are_visible(self):
        self.vlc.side_effect = FileNotFoundError('VLC fehlt')
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 400)
        self.assertIn('VLC fehlt', response.get_json()['error'])
        self.vlc.side_effect = None
        self.popen.side_effect = OSError('Start fehlgeschlagen')
        self.assertEqual(self.client.post(self.url).status_code, 400)
        self.popen.side_effect = None
        self.popen.return_value.wait.side_effect = None
        self.popen.return_value.wait.return_value = 1
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 400)
        self.assertIn('Exit-Code 1', response.get_json()['error'])

    def test_translation_start_state_is_exposed(self):
        url = f'/api/status/{self.project_id}'
        self.assertFalse(self.client.get(url).get_json()['translation_started'])
        self.assertTrue(acquire_translation_lock(self.project_id, 'test-worker'))
        self.assertTrue(self.client.get(url).get_json()['translation_started'])


class VlcDiscoveryTests(unittest.TestCase):
    def test_explicit_path_and_invalid_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / 'vlc.exe'
            executable.write_bytes(b'test executable')
            with patch.dict('os.environ', {'SUBTRANSLATE_VLC_PATH': str(executable)}):
                self.assertEqual(find_vlc(), str(executable))
                executable.unlink()
                with self.assertRaisesRegex(FileNotFoundError, 'SUBTRANSLATE_VLC_PATH'):
                    find_vlc()

    def test_windows_standard_location(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / 'VideoLAN' / 'VLC' / 'vlc.exe'
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b'test executable')
            with patch.dict('os.environ', {'ProgramFiles(x86)': directory}, clear=True):
                with patch('app.services.media_player_service.shutil.which', return_value=None):
                    self.assertEqual(find_vlc(), str(executable))
                    executable.unlink()
                    with self.assertRaisesRegex(FileNotFoundError, 'VLC wurde nicht gefunden'):
                        find_vlc()


if __name__ == '__main__':
    unittest.main()
