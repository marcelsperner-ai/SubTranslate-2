import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services.translation_service import translate_batch


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.models = self

    def generate_content(self, model, contents, config):
        self.requests.append(json.loads(contents))
        entries = self.responses.pop(0)
        return SimpleNamespace(text=json.dumps(entries), parsed=entries)


def entries(sources, texts, start=1):
    return [
        {"id": i, "source": source, "text": text}
        for i, (source, text) in enumerate(zip(sources, texts), start)
    ]


class TranslateBatchTests(unittest.TestCase):
    def setUp(self):
        patcher = patch('builtins.print')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_sends_ids_and_returns_texts_in_order(self):
        client = FakeClient([entries(['A', 'B'], ['الف', 'ب'])])

        result = translate_batch(client, ['A', 'B'], 'prompt', lambda _: None)

        self.assertEqual(result, ['الف', 'ب'])
        self.assertEqual(client.requests[0], [{"id": 1, "text": "A"}, {"id": 2, "text": "B"}])

    def test_shifted_ids_with_correct_length_split_the_batch(self):
        shifted = entries(['B', 'C', 'B'], ['ب', 'ج', 'ب'], start=2)
        client = FakeClient([shifted, entries(['A'], ['الف']), entries(['B', 'C'], ['ب', 'ج'])])

        result = translate_batch(client, ['A', 'B', 'C'], 'prompt', lambda _: None)

        self.assertEqual(result, ['الف', 'ب', 'ج'])
        self.assertEqual([len(request) for request in client.requests], [3, 1, 2])

    def test_duplicate_or_skipped_ids_are_rejected(self):
        client = FakeClient([
            entries(['A', 'B'], ['الف', 'ب']),
            [{"id": 1, "source": "A", "text": "الف"}, {"id": 1, "source": "B", "text": "ب"}],
        ])
        logs = []

        with patch('app.services.translation_service.time.sleep'):
            result = translate_batch(client, ['A'], 'prompt', logs.append, max_retries=1)

        self.assertIsNone(result)
        self.assertTrue(any('Zuordnungs-Mismatch' in log for log in logs))

    def test_shifted_content_with_correct_ids_is_detected_by_source(self):
        shifted = entries(['B', 'C', 'C'], ['ب', 'ج', 'ج'])
        client = FakeClient([shifted, entries(['A'], ['الف']), entries(['B', 'C'], ['ب', 'ج'])])

        result = translate_batch(client, ['A', 'B', 'C'], 'prompt', lambda _: None)

        self.assertEqual(result, ['الف', 'ب', 'ج'])
        self.assertEqual([len(request) for request in client.requests], [3, 1, 2])

    def test_writes_raw_responses_to_debug_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / 'debug' / 'raw.jsonl'
            client = FakeClient([entries(['A'], ['الف'])])

            translate_batch(client, ['A'], 'prompt', lambda _: None, debug_log_path=str(log_path))

            record = json.loads(log_path.read_text(encoding='utf-8'))
            self.assertTrue(record['ids_ok'])
            self.assertEqual(record['source_mismatches'], [])
            self.assertEqual(record['request'], [{"id": 1, "text": "A"}])


if __name__ == '__main__':
    unittest.main()
