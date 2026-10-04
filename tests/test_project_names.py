import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app
from app.db import create_translation, save_export_location


class ProjectNameTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / 'translations.db'
        self.db_path_patcher = patch('app.db.DB_PATH', str(self.db_path))
        self.db_path_patcher.start()
        self.addCleanup(self.db_path_patcher.stop)
        self.app = create_app()
        self.app.config['OUTPUTS_DIR'] = self.temp_dir.name
        with self.app.app_context():
            self.project_id = create_translation(
                'source.srt', 10, 0, 'tatortreiniger', '1x1'
            )
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_project_lists_use_suggested_name_and_keep_original_filename(self):
        project = self.client.get('/api/projects').get_json()[0]
        self.assertEqual(project['project_name'], 'Tatortreiniger 1.1')
        self.assertEqual(project['original_filename'], 'source.srt')

    def test_rename_is_persisted_without_changing_original_filename(self):
        response = self.client.put(
            f'/api/project/{self.project_id}/name',
            json={'project_name': '  Currywurst  '}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['project_name'], 'Currywurst')

        project = self.client.get(f'/api/project/{self.project_id}').get_json()
        self.assertEqual(project['project_name'], 'Currywurst')
        self.assertEqual(project['original_filename'], 'source.srt')

    def test_rename_rejects_blank_and_overlong_names(self):
        blank_response = self.client.put(
            f'/api/project/{self.project_id}/name', json={'project_name': '   '}
        )
        overlong_response = self.client.put(
            f'/api/project/{self.project_id}/name', json={'project_name': 'x' * 121}
        )
        self.assertEqual(blank_response.status_code, 400)
        self.assertEqual(overlong_response.status_code, 400)

    def test_export_targets_report_configured_filename_and_existing_copy(self):
        subtitles_dir = self.db_path.parent / 'subtitle_exports'
        vocab_dir = self.db_path.parent / 'vocab_exports'
        subtitles_dir.mkdir()
        with self.app.app_context():
            save_export_location('tatortreiniger', '1', str(subtitles_dir), str(vocab_dir))
        (subtitles_dir / 'source_FA.srt').write_text('existing', encoding='utf-8')

        response = self.client.get(
            f'/api/project/{self.project_id}/export-targets?types=srt,csv,ass'
        )

        self.assertEqual(response.status_code, 200)
        targets = response.get_json()['targets']
        self.assertEqual(targets['srt']['filename'], 'source_FA.srt')
        self.assertTrue(targets['srt']['exists'])
        self.assertFalse(targets['ass']['exists'])
        self.assertEqual(targets['csv']['directory'], str(vocab_dir))

        alternate_response = self.client.get(
            f'/api/project/{self.project_id}/export-targets?types=srt&filename=alternate'
        )
        self.assertEqual(alternate_response.get_json()['targets']['srt']['filename'], 'alternate.srt')
        (subtitles_dir / 'alternate.srt').write_text('existing alternate', encoding='utf-8')
        collision_response = self.client.get(
            f'/api/project/{self.project_id}/export-targets?types=srt&filename=alternate.srt'
        )
        self.assertTrue(collision_response.get_json()['targets']['srt']['exists'])
        unsafe_response = self.client.get(
            f'/api/project/{self.project_id}/export-targets?types=srt&filename=..%2Foutside.srt'
        )
        self.assertEqual(unsafe_response.status_code, 400)


if __name__ == '__main__':
    unittest.main()