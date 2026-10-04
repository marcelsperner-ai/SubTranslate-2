import csv
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import app.services.edtech_service as edtech_service


CSV_FIELDS = [
    'Cue_ID', 'Zeitstempel', 'Farsi_Keyword', 'Farsi_Hervorhebung', 'German_Quote', 'Deutsches_Wort',
    'Erklärung auf Farsi', 'Erklärung im Kontext der Geschichte',
    'Semantik_Status', 'Semantik_Hinweis',
]


class FakeParsedItem:
    def __init__(self, values):
        self.values = values

    def model_dump(self):
        return self.values


class FakeModels:
    def __init__(self, vocabulary_count=25, semantic_warning=False, misassign_first=False):
        self.calls = 0
        self.vocabulary_count = vocabulary_count
        self.semantic_warning = semantic_warning
        self.misassign_first = misassign_first

    def generate_content(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            cue_ids = range(1, self.vocabulary_count + 1)
            items = [
                FakeParsedItem({
                    'cue_id': 2 if self.misassign_first and cue_id == 1 else (cue_id - 1) % 25 + 1,
                    'german_quote': f'Wort{cue_id}',
                    'wort_deutsch': f'Wort{cue_id}',
                    'keyword_farsi': f'واژه{cue_id}',
                    'highlight_farsi': f'واژه{cue_id}',
                    'erklaerung_farsi': f'معنی{cue_id}',
                    'erklaerung_kontext': f'Kontext {cue_id}',
                })
                for cue_id in cue_ids
            ]
        else:
            items = [
                FakeParsedItem({
                    'item_id': cue_id,
                    'aligned': not (self.semantic_warning and cue_id == 1),
                    'reason': 'Bedeutung manuell prüfen' if self.semantic_warning and cue_id == 1 else '',
                })
                for cue_id in range(1, self.vocabulary_count + 1)
            ]
        return SimpleNamespace(parsed=items, text='')


class FakeClient:
    def __init__(self, **kwargs):
        self.models = FakeModels()


class EdTechValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.german_path = self.root / 'source.srt'
        self.farsi_path = self.root / 'source_FA.srt'
        self.csv_path = self.root / 'source_Vokabeln.csv'
        self.ass_path = self.root / 'source_Interaktiv.ass'
        self.german_subtitles = []
        self.farsi_subtitles = []
        for cue_id in range(1, 26):
            start = cue_id * 2
            timing = f'00:00:{start:02d},000 --> 00:00:{start + 1:02d},000'
            self.german_subtitles.append(f'{cue_id}\n{timing}\nDas Wort Wort{cue_id} kommt vor.')
            self.farsi_subtitles.append(f'{cue_id}\n{timing}\nترجمه واژه{cue_id}')
        self.german_path.write_text('\n\n'.join(self.german_subtitles), encoding='utf-8')
        self.farsi_path.write_text('\n\n'.join(self.farsi_subtitles), encoding='utf-8')

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_valid_csv(self):
        rows = []
        for cue_id in range(1, 26):
            rows.append({
                'Cue_ID': cue_id,
                'Zeitstempel': f'00:00:{cue_id * 2:02d},000',
                'Farsi_Keyword': f'واژه{cue_id}',
                'Farsi_Hervorhebung': f'واژه{cue_id}',
                'German_Quote': f'Wort{cue_id}',
                'Deutsches_Wort': f'Wort{cue_id}',
                'Erklärung auf Farsi': f'معنی{cue_id}',
                'Erklärung im Kontext der Geschichte': f'Kontext {cue_id}',
                'Semantik_Status': 'OK',
                'Semantik_Hinweis': '',
            })
        with self.csv_path.open('w', encoding='utf-8-sig', newline='') as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        return rows

    def test_csv_validation_uses_only_the_assigned_cue(self):
        rows = self.write_valid_csv()
        self.german_subtitles[0] = '1\n00:00:02,000 --> 00:00:03,000\nDer Sohn.'
        self.german_subtitles[1] = '2\n00:00:04,000 --> 00:00:05,000\nEin kurzer Weg.'
        self.farsi_subtitles[0] = '1\n00:00:02,000 --> 00:00:03,000\nپسرش'
        self.farsi_subtitles[1] = '2\n00:00:04,000 --> 00:00:05,000\nیه سر برم بیرون'
        self.german_path.write_text('\n\n'.join(self.german_subtitles), encoding='utf-8')
        self.farsi_path.write_text('\n\n'.join(self.farsi_subtitles), encoding='utf-8')
        rows[0].update({
            'Farsi_Keyword': 'سر',
            'Farsi_Hervorhebung': 'سر',
            'German_Quote': 'Der Sohn',
            'Deutsches_Wort': 'Sohn',
        })
        rows.append(dict(rows[0]))
        with self.csv_path.open('w', encoding='utf-8-sig', newline='') as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(rows)

        report = edtech_service.validate_edtech_csv(
            str(self.german_path), str(self.farsi_path), str(self.csv_path)
        )
        cue_one_mismatches = [item for item in report['kw_mismatches'] if item['cue_id'] == 1]
        self.assertEqual(len(cue_one_mismatches), 2)
        self.assertEqual(cue_one_mismatches[0]['other_cue_ids'], [2])
        self.assertTrue(any('Doppeltes Keyword' in issue['message'] for issue in report['data_issues']))
        self.assertFalse(report['ts_mismatches'])

    def test_semantic_keyword_can_use_exact_distinct_highlight_phrase(self):
        rows = self.write_valid_csv()
        rows[0]['Farsi_Keyword'] = 'مفهوم'
        rows[0]['Farsi_Hervorhebung'] = 'ترجمه'
        with self.csv_path.open('w', encoding='utf-8-sig', newline='') as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(rows)

        report = edtech_service.validate_edtech_csv(
            str(self.german_path), str(self.farsi_path), str(self.csv_path)
        )
        self.assertFalse([item for item in report['kw_mismatches'] if item['cue_id'] == 1])

        edtech_service.generate_learning_subtitles(
            str(self.farsi_path), str(self.ass_path), german_srt_path=str(self.german_path),
            csv_filepath=str(self.csv_path), highlight_underline=True,
        )
        dialogue = next(
            line for line in self.ass_path.read_text(encoding='utf-8').splitlines()
            if line.startswith('Dialogue: 0,0:00:02.00,')
        )
        self.assertIn(r'{\u1}ترجمه{\u0}', dialogue)
        self.assertNotIn(r'{\u1}مفهوم{\u0}', dialogue)

    def test_generator_converts_srt_italics_to_ass_overrides(self):
        self.write_valid_csv()
        self.farsi_subtitles[0] = (
            '1\n00:00:02,000 --> 00:00:03,000\n<I>ترجمه</I> واژه1'
        )
        self.farsi_path.write_text('\n\n'.join(self.farsi_subtitles), encoding='utf-8')

        edtech_service.generate_learning_subtitles(
            str(self.farsi_path), str(self.ass_path), german_srt_path=str(self.german_path),
            csv_filepath=str(self.csv_path),
        )

        dialogue = next(
            line for line in self.ass_path.read_text(encoding='utf-8').splitlines()
            if line.startswith('Dialogue: 0,0:00:02.00,')
        )
        self.assertIn(r'{\i1}ترجمه{\i0}', dialogue)
        self.assertNotIn('<I>', dialogue)
        self.assertNotIn('</I>', dialogue)

    def test_invalid_highlight_is_reported_and_not_applied(self):
        rows = self.write_valid_csv()
        rows[0]['Farsi_Hervorhebung'] = 'متن غایب'
        with self.csv_path.open('w', encoding='utf-8-sig', newline='') as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(rows)

        report = edtech_service.validate_edtech_csv(
            str(self.german_path), str(self.farsi_path), str(self.csv_path)
        )
        mismatch = next(item for item in report['kw_mismatches'] if item['cue_id'] == 1)
        self.assertEqual(mismatch['field'], 'Farsi_Hervorhebung')

        edtech_service.generate_learning_subtitles(
            str(self.farsi_path), str(self.ass_path), german_srt_path=str(self.german_path),
            csv_filepath=str(self.csv_path), highlight_underline=True,
        )
        dialogue = next(
            line for line in self.ass_path.read_text(encoding='utf-8').splitlines()
            if line.startswith('Dialogue: 0,0:00:02.00,')
        )
        self.assertNotIn(r'{\u1}', dialogue)

    def test_generator_writes_cue_ids_and_semantic_warnings(self):
        fake_client = FakeClient()
        fake_client.models = FakeModels(semantic_warning=True)
        with patch.object(edtech_service.genai, 'Client', return_value=fake_client):
            edtech_service.generate_learning_subtitles(
                str(self.farsi_path),
                str(self.ass_path),
                german_srt_path=str(self.german_path),
                csv_filepath=str(self.csv_path),
                api_key='test-key',
                force_csv_regeneration=True,
                highlight_underline=True,
            )

        with self.csv_path.open(encoding='utf-8-sig', newline='') as csv_file:
            rows = list(csv.DictReader(csv_file))
        self.assertEqual(len(rows), 25)
        self.assertEqual(rows[0]['Cue_ID'], '1')
        self.assertEqual(rows[0]['Zeitstempel'], '00:00:02,000')
        self.assertEqual(rows[0]['Farsi_Hervorhebung'], 'واژه1')
        self.assertEqual(rows[0]['Semantik_Status'], 'PRÜFEN')
        ass_text = self.ass_path.read_text(encoding='utf-8')
        first_dialogue = next(
            line.split(',', 9)[9]
            for line in ass_text.splitlines()
            if line.startswith('Dialogue: 0,0:00:02.00,')
        )
        segments = first_dialogue.split(r'\N')
        self.assertEqual(len(segments), 2)
        self.assertIn(r'{\u1}واژه1{\u0}', segments[-1])

    def test_generator_corrects_only_a_unique_paired_cue_assignment(self):
        fake_client = FakeClient()
        fake_client.models = FakeModels(misassign_first=True)
        with patch.object(edtech_service.genai, 'Client', return_value=fake_client):
            edtech_service.generate_learning_subtitles(
                str(self.farsi_path),
                str(self.ass_path),
                german_srt_path=str(self.german_path),
                csv_filepath=str(self.csv_path),
                api_key='test-key',
                force_csv_regeneration=True,
            )
        with self.csv_path.open(encoding='utf-8-sig', newline='') as csv_file:
            rows = list(csv.DictReader(csv_file))
        self.assertEqual(rows[0]['Cue_ID'], '1')
        self.assertEqual(rows[0]['Zeitstempel'], '00:00:02,000')

    def test_ambiguous_paired_cues_are_not_reassigned(self):
        self.german_subtitles[1] = '2\n00:00:04,000 --> 00:00:05,000\nDas Wort Wort1 kommt vor.'
        self.farsi_subtitles[1] = '2\n00:00:04,000 --> 00:00:05,000\nترجمه واژه1'
        self.german_path.write_text('\n\n'.join(self.german_subtitles), encoding='utf-8')
        self.farsi_path.write_text('\n\n'.join(self.farsi_subtitles), encoding='utf-8')
        cues = edtech_service.paired_subtitle_cues(str(self.german_path), str(self.farsi_path))
        row = {
            'Cue_ID': 3,
            'Zeitstempel': '00:00:06,000',
            'Farsi_Keyword': 'واژه1',
            'German_Quote': 'Wort1',
            'Deutsches_Wort': 'Wort1',
        }
        self.assertEqual(edtech_service.vocabulary_cue_candidates(row, cues), [1, 2])
        edtech_service.canonicalize_vocabulary_cues([row], cues)
        self.assertEqual(row['Cue_ID'], 3)

    def test_generation_above_recommended_vocabulary_count_writes_csv_and_ass(self):
        fake_client = FakeClient()
        fake_client.models = FakeModels(vocabulary_count=36)
        with patch.object(edtech_service.genai, 'Client', return_value=fake_client):
            ass_path, csv_path = edtech_service.generate_learning_subtitles(
                str(self.farsi_path),
                str(self.ass_path),
                german_srt_path=str(self.german_path),
                csv_filepath=str(self.csv_path),
                api_key='test-key',
                force_csv_regeneration=True,
            )

        with self.csv_path.open(encoding='utf-8-sig', newline='') as csv_file:
            rows = list(csv.DictReader(csv_file))
        self.assertEqual(len(rows), 36)
        self.assertTrue(Path(ass_path).is_file())
        self.assertTrue(Path(csv_path).is_file())

    def test_failed_ass_validation_keeps_existing_ass(self):
        self.write_valid_csv()
        self.ass_path.write_text('previous ASS content', encoding='utf-8')
        with patch.object(edtech_service, 'validate_ass_content', return_value=['forced validation failure']):
            with self.assertRaisesRegex(ValueError, 'ASS-Prüfung fehlgeschlagen'):
                edtech_service.generate_learning_subtitles(
                    str(self.farsi_path),
                    str(self.ass_path),
                    german_srt_path=str(self.german_path),
                    csv_filepath=str(self.csv_path),
                    highlight_underline=True,
                )
        self.assertEqual(self.ass_path.read_text(encoding='utf-8'), 'previous ASS content')
        self.assertEqual(list(self.root.glob('*.tmp')), [])


if __name__ == '__main__':
    unittest.main()

class WordFormVerificationTests(unittest.TestCase):
    def test_inflected_form_is_found(self):
        self.assertEqual(edtech_service.verify_word_form('Spinnt ihr jetzt hier alle?', 'Spinnt', '', 'spinnen')[0], 'OK')
        self.assertEqual(edtech_service.verify_word_form("Kapier's grad nicht.", "Kapier's", '', 'kapieren')[0], 'OK')

    def test_segments_must_follow_quote_order(self):
        self.assertEqual(edtech_service.verify_word_form('Ich hau jetzt ab!', '', 'hau|ab', 'abhauen')[0], 'OK')
        self.assertEqual(edtech_service.verify_word_form('Ich hau jetzt ab!', '', 'ab|hau', 'abhauen')[0], 'PRÜFEN')

    def test_form_missing_in_quote_is_flagged(self):
        self.assertEqual(edtech_service.verify_word_form('Ich hau jetzt ab!', 'spinnt', '', 'spinnen')[0], 'PRÜFEN')
        self.assertEqual(edtech_service.verify_word_form('Ich hau jetzt ab!', '', '', 'abhauen')[0], 'PRÜFEN')

    def test_quote_identical_to_word_is_not_cloze_capable(self):
        self.assertEqual(edtech_service.verify_word_form('Mal langsam.', '', '', 'Mal langsam!')[0], 'KEINE_LÜCKE')
        self.assertEqual(edtech_service.verify_word_form('Moin.', 'Moin', '', 'Moin')[0], 'KEINE_LÜCKE')

    def test_failed_forms_are_corrected_by_followup_call(self):
        rows = [{'cue_id': 1, 'german_quote': 'Spinnt ihr jetzt?', 'wort_deutsch': 'spinnen',
                 'wortform_im_zitat': 'spinnen', 'luecken_segmente': ''}]
        cues = [{'cue_id': 1, 'german_text': 'Spinnt ihr jetzt?', 'farsi_text': '', 'zeit': ''}]
        fix = {'item_id': 1, 'wortform_im_zitat': 'Spinnt', 'luecken_segmente': ''}
        client = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kw: SimpleNamespace(
            parsed=[SimpleNamespace(model_dump=lambda: fix)], usage_metadata=None)))
        edtech_service._verify_and_fix_word_forms(client, 'm', rows, cues)
        self.assertEqual(rows[0]['form_status'], 'OK')
        self.assertEqual(rows[0]['wortform_im_zitat'], 'Spinnt')


class WordFormPostProcessingTests(unittest.TestCase):
    def test_weak_single_token_for_separable_verb_is_flagged(self):
        verify = edtech_service.verify_word_form
        self.assertEqual(verify('Hier unten bekommt man vieles nicht mit.', 'mit', '', 'etwas mitkriegen')[0], 'PRÜFEN')
        self.assertEqual(verify('Ein Kumpel von mir legt da auf.', 'legt', '', 'auflegen')[0], 'PRÜFEN')
        self.assertEqual(verify('Ein Kumpel von mir legt da auf.', '', 'legt|auf', 'auflegen')[0], 'OK')

    def test_closed_verb_forms_stay_ok(self):
        verify = edtech_service.verify_word_form
        self.assertEqual(verify('Der hat mich mal angebaggert.', 'angebaggert', '', 'jemanden anbaggern')[0], 'OK')
        self.assertEqual(verify('Du bist ja abgehauen.', 'abgehauen', '', 'abhauen')[0], 'OK')
        self.assertEqual(verify('Einfach mal Emotionen raushauen.', 'raushauen', '', 'etwas raushauen')[0], 'OK')
        self.assertEqual(verify('Spinnt ihr jetzt?', 'Spinnt', '', 'spinnen')[0], 'OK')

    def test_cleaning_and_register_normalization(self):
        rows = [{'wort_deutsch': 'Mal langsam!', 'german_quote': '# Krass, krass ...', 'wortform_im_zitat': ' Krass ',
                 'stilregister': 'Redewendung'},
                {'wort_deutsch': 'Kacke', 'german_quote': 'Kacke.', 'wortform_im_zitat': '', 'stilregister': 'Derb'}]
        edtech_service._clean_vocabulary(rows)
        self.assertEqual(rows[0]['wort_deutsch'], 'Mal langsam')
        self.assertEqual(rows[0]['german_quote'], 'Krass, krass ...')
        self.assertEqual(rows[0]['stilregister'], '')
        self.assertEqual(rows[1]['stilregister'], 'derb')

    def test_duplicate_lemma_gets_hint_only(self):
        rows = [{'cue_id': 326, 'wort_deutsch': 'abhauen'}, {'cue_id': 411, 'wort_deutsch': 'abhauen'}]
        edtech_service._flag_duplicate_lemmas(rows)
        self.assertNotIn('form_hinweis', rows[0])
        self.assertIn('326', rows[1]['form_hinweis'])


class LongWordFormTests(unittest.TestCase):
    def test_overlong_form_is_flagged_and_segments_are_ok(self):
        verify = edtech_service.verify_word_form
        quote = 'Aber ich frier mir nicht wieder den Arsch ab.'
        self.assertEqual(verify(quote, 'frier mir nicht wieder den Arsch ab', '', 'sich den Arsch abfrieren')[0], 'PRÜFEN')
        self.assertEqual(verify(quote, '', 'frier|den Arsch ab', 'sich den Arsch abfrieren')[0], 'OK')


class WholeQuoteLengthTests(unittest.TestCase):
    def test_long_whole_quote_form_is_flagged_but_short_one_is_not(self):
        verify = edtech_service.verify_word_form
        self.assertEqual(verify('Sagt mir leider gar nix.', 'Sagt mir leider gar nix', '', 'jemandem nichts sagen')[0], 'PRÜFEN')
        self.assertEqual(verify('Sagt mir leider gar nix.', '', 'Sagt|nix', 'jemandem nichts sagen')[0], 'OK')
        self.assertEqual(verify('Mein lieber Gesangverein.', 'Mein lieber Gesangverein', '', 'Mein lieber Gesangverein')[0], 'KEINE_LÜCKE')
