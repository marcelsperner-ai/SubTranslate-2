import tempfile
import unittest
from pathlib import Path

from app.services.export_service import copy_file_to_export


class ExportServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source = self.root / 'source_FA.srt'
        self.export_dir = self.root / 'export'
        self.source.write_text('new subtitle', encoding='utf-8')

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_copies_under_requested_filename_without_overwriting_existing_file(self):
        target = self.export_dir / 'renamed.srt'
        target.parent.mkdir()
        target.write_text('existing subtitle', encoding='utf-8')

        copied = copy_file_to_export(
            str(self.source), str(self.export_dir),
            export_options={'filename': 'renamed.srt', 'overwrite': False},
        )

        self.assertFalse(copied)
        self.assertEqual(target.read_text(encoding='utf-8'), 'existing subtitle')

    def test_overwrites_only_when_explicitly_requested(self):
        target = self.export_dir / 'source_FA.srt'
        target.parent.mkdir()
        target.write_text('existing subtitle', encoding='utf-8')

        copied = copy_file_to_export(
            str(self.source), str(self.export_dir),
            export_options={'filename': 'source_FA.srt', 'overwrite': True},
        )

        self.assertTrue(copied)
        self.assertEqual(target.read_text(encoding='utf-8'), 'new subtitle')

    def test_rejects_export_paths_and_different_extensions(self):
        with self.assertRaisesRegex(ValueError, 'keinen Pfad'):
            copy_file_to_export(
                str(self.source), str(self.export_dir),
                export_options={'filename': '../outside.srt'},
            )
        with self.assertRaisesRegex(ValueError, 'Dateiendung'):
            copy_file_to_export(
                str(self.source), str(self.export_dir),
                export_options={'filename': 'renamed.ass'},
            )


if __name__ == '__main__':
    unittest.main()