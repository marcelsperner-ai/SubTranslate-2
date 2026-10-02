import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from app import create_app
import app.db as db
from app.services.subtitle_conversion_service import convert_ttml_to_srt


TTML_SAMPLE = b'''<?xml version="1.0" encoding="UTF-8"?>
<tt:tt xmlns:tt="http://www.w3.org/ns/ttml" xmlns:tts="http://www.w3.org/ns/ttml#styling">
  <tt:head><tt:styling><tt:style xml:id="speaker" tts:color="#00FF00" /></tt:styling></tt:head>
  <tt:body><tt:div>
    <tt:p begin="00:00:01.200" end="00:00:02.500">
      <tt:span style="speaker">Hallo</tt:span><tt:br /><tt:span style="speaker">Welt</tt:span>
    </tt:p>
  </tt:div></tt:body>
</tt:tt>'''


class SubtitleConversionTests(unittest.TestCase):
    def test_converts_ttml_clock_times_colors_and_line_breaks(self):
        srt = convert_ttml_to_srt(TTML_SAMPLE)

        self.assertIn('1\n00:00:01,200 --> 00:00:02,500', srt)
        self.assertIn(
            '<font color="#00FF00">Hallo</font>\n<font color="#00FF00">Welt</font>',
            srt,
        )

    def test_xml_upload_keeps_original_and_creates_srt_project(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path_patcher = patch('app.db.DB_PATH', str(root / 'translations.db'))
            db_path_patcher.start()
            self.addCleanup(db_path_patcher.stop)
            app = create_app()
            app.config['UPLOADS_DIR'] = str(root / 'uploads')
            app.config['OUTPUTS_DIR'] = str(root / 'outputs')
            Path(app.config['UPLOADS_DIR']).mkdir()
            client = app.test_client()

            response = client.post('/api/upload', data={
                'file': (BytesIO(TTML_SAMPLE), 'sample.xml'),
            }, content_type='multipart/form-data')

            self.assertEqual(response.status_code, 201, response.get_json())
            self.assertEqual(response.get_json()['original_filename'], 'sample.srt')
            self.assertEqual(response.get_json()['source_format'], 'ttml')
            self.assertEqual((root / 'uploads' / 'sample.xml').read_bytes(), TTML_SAMPLE)
            converted = (root / 'uploads' / 'sample.srt').read_text(encoding='utf-8')
            self.assertIn('<font color="#00FF00">Hallo</font>', converted)

    def test_ttml_content_with_srt_extension_does_not_overwrite_conversion(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path_patcher = patch('app.db.DB_PATH', str(root / 'translations.db'))
            db_path_patcher.start()
            self.addCleanup(db_path_patcher.stop)
            app = create_app()
            app.config['UPLOADS_DIR'] = str(root / 'uploads')
            app.config['OUTPUTS_DIR'] = str(root / 'outputs')
            Path(app.config['UPLOADS_DIR']).mkdir()
            client = app.test_client()

            response = client.post('/api/upload', data={
                'file': (BytesIO(TTML_SAMPLE), 'sample.srt'),
            }, content_type='multipart/form-data')

            self.assertEqual(response.status_code, 201, response.get_json())
            payload = response.get_json()
            self.assertEqual(payload['source_filename'], 'sample.source.xml')
            self.assertIn('00:00:01,200 --> 00:00:02,500', (root / 'uploads' / 'sample.srt').read_text(encoding='utf-8'))
            self.assertEqual((root / 'uploads' / 'sample.source.xml').read_bytes(), TTML_SAMPLE)

    def test_invalid_ttml_upload_returns_bad_request_without_saving_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path_patcher = patch('app.db.DB_PATH', str(root / 'translations.db'))
            db_path_patcher.start()
            self.addCleanup(db_path_patcher.stop)
            app = create_app()
            app.config['UPLOADS_DIR'] = str(root / 'uploads')
            app.config['OUTPUTS_DIR'] = str(root / 'outputs')
            Path(app.config['UPLOADS_DIR']).mkdir()
            client = app.test_client()

            response = client.post('/api/upload', data={
                'file': (BytesIO(b'<tt:tt>'), 'broken.xml'),
            }, content_type='multipart/form-data')

            self.assertEqual(response.status_code, 400)
            self.assertFalse((root / 'uploads' / 'broken.xml').exists())


if __name__ == '__main__':
    unittest.main()
