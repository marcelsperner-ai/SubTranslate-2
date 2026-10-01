import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app
from app.db import create_translation


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


if __name__ == '__main__':
    unittest.main()