import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app
from app.db import create_translation
from app.services.edtech_service import EDTECH_CSV_COLUMNS, EDTECH_GENERATION_INSTRUCTIONS


class EdtechPromptTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / 'translations.db'
        self.db_path_patcher = patch('app.db.DB_PATH', str(self.db_path))
        self.db_path_patcher.start()
        self.addCleanup(self.db_path_patcher.stop)
        self.app = create_app()
        with self.app.app_context():
            self.project_id = create_translation(
                'source.srt', 10, 0, 'tatortreiniger', '1x1'
            )
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_edtech_prompt_is_saved_and_returned_for_its_project(self):
        custom_prompt = 'Mein dauerhafter Projektprompt'
        response = self.client.put(
            f'/api/edtech/prompt/{self.project_id}',
            json={'prompt': custom_prompt}
        )
        self.assertEqual(response.status_code, 200)

        prompts = self.client.get(f'/api/prompts/{self.project_id}').get_json()
        self.assertEqual(prompts['edtech_prompt'], custom_prompt)
        self.assertTrue(prompts['edtech_prompt_is_custom'])

    def test_prompt_payload_exposes_csv_generation_instructions_and_columns(self):
        prompts = self.client.get(f'/api/prompts/{self.project_id}').get_json()
        self.assertEqual(
            prompts['edtech_generation_instructions'],
            EDTECH_GENERATION_INSTRUCTIONS
        )
        self.assertEqual(prompts['edtech_csv_columns'], list(EDTECH_CSV_COLUMNS))

    def test_edtech_prompt_rejects_blank_text(self):
        response = self.client.put(
            f'/api/edtech/prompt/{self.project_id}',
            json={'prompt': '  '}
        )
        self.assertEqual(response.status_code, 400)


if __name__ == '__main__':
    unittest.main()
