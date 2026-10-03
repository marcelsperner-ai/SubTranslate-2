import os
import re
import csv
import json
import logging
from io import StringIO
from datetime import datetime, timedelta
from google import genai
from google.genai import types
import pysrt
from pydantic import BaseModel
from app.prompt_manager import append_episode_summary

logger = logging.getLogger(__name__)

EDTECH_GENERATION_INSTRUCTIONS = """Erstelle bis zu 35 Vokabeleinträge aus den exakt gepaarten Untertiteln. Qualität vor Menge: nimm nur Einträge, deren deutsche und persische Stelle eindeutig demselben Cue zugeordnet werden können.
Jeder Eintrag hat zwei Verwendungen: (A) eine Infobox, die die Grundform (Lemma) zeigt, und (B) Lernmodi (Karteikarte, Lückentext), die die tatsächliche Wortform im Zitat unterstreichen bzw. ausblenden. Dafür gibt es getrennte Felder.
Felder je Eintrag:
1. "cue_id": die Nummer des Untertitels, aus dem das deutsche Wort und Farsi-Keyword stammen.
2. "german_quote": wortgetreues deutsches Zitat aus genau diesem Untertitel. Es soll der vollständige Satz oder Teilsatz aus dem Cue sein, nicht nur die Wendung selbst.
3. "wort_deutsch": Grundform für die Infobox (Infinitiv, Singular, ggf. mit Artikel oder "jemanden/etwas"; feste Wendungen in Grundform). Immer ein vollständiger, eigenständiger Ausdruck, kein Satzfragment (nicht "von ganz oben", sondern z.B. "die Riege"). Keine Satzzeichen, auch kein "!" oder "?" am Ende.
4. "wortform_im_zitat": die Textstelle in german_quote, die dem Wort entspricht. MUSS eine zusammenhängende, zeichengenaue Teilzeichenkette von german_quote sein (inkl. Beugung, z.B. "Spinnt" für "spinnen", "angebaggert" für "anbaggern"). Darf nicht der ganze Satz sein und höchstens 4 Wörter umfassen. Leer lassen, wenn "luecken_segmente" gesetzt ist.
5. "luecken_segmente": PFLICHT bei trennbaren Verben, deren Teile im Zitat getrennt stehen, und bei mehrteiligen Wendungen mit Lücke dazwischen (z.B. "in Rechnung stellen"): ALLE Bestandteile zeichengenau in Reihenfolge des Zitats, getrennt durch "|". Auch Verb und Präfix/Partikel gehören dazu: "bekommt|mit" (mitkriegen), "legt|auf" (auflegen), "hau|ab" (abhauen). Wortform allein (nur "mit" oder "legt") ist falsch. Bei langen Wendungen nur die Kernbestandteile als Segmente, Füllwörter (mir, mich, nicht, wieder, noch, da, ...) weglassen: "frier|den Arsch ab", "bringst|ins Grab". Steht das Verb am Stück (z.B. "abgehauen", "aufzumachen"), genügt wortform_im_zitat. Sonst leerer String.
6. "keyword_farsi": Bedeutung des deutschen Ausdrucks auf Farsi; darf sinngemäß formuliert sein.
7. "highlight_farsi": eine kurze, exakt und zusammenhängend aus dem Farsi-Text desselben Cues kopierte Stelle, die in den Untertiteln hervorgehoben wird. Keine Übersetzung oder Umformulierung. Wenn sich keine passende Stelle findet, leer lassen.
8. "erklaerung_farsi": Bedeutung auf Farsi.
9. "erklaerung_kontext": kurzer deutscher Satz zur Handlung.
10. "stilregister": genau einer dieser Werte oder leer: "norddeutsch", "umgangssprachlich", "derb", "Jugendsprache", "gehoben". Nur setzen, wenn der Ausdruck auffällig vom neutralen Standarddeutsch abweicht; höchstens bei einem Drittel aller Einträge. Kein "Redewendung" oder ähnliche Typangaben, sonst leer.
Regeln: wort_deutsch und german_quote dürfen nicht bis auf Satzzeichen identisch sein. Bei Grüßen/Interjektionen mit sehr kurzem Zitat (z.B. "Moin.") ist das nur erlaubt, wenn der Cue nicht mehr Text enthält; dann wortform_im_zitat leer lassen. german_quote enthält keine Musik- oder Sprecherzeichen (#, ♪, -).
Beispiele:
- Zitat "Spinnt ihr jetzt hier alle?" -> wort_deutsch "spinnen", wortform_im_zitat "Spinnt", luecken_segmente "".
- Zitat "Ich hau jetzt ab!" -> wort_deutsch "abhauen", wortform_im_zitat "", luecken_segmente "hau|ab".
- Zitat "Hier unten bekommt man vieles nicht mit." -> wort_deutsch "etwas mitkriegen", wortform_im_zitat "", luecken_segmente "bekommt|mit".
- Zitat "Der hat mich mal angebaggert." -> wort_deutsch "jemanden anbaggern", wortform_im_zitat "angebaggert", luecken_segmente "".
- Farsi_Keyword darf sinngemäß sein; highlight_farsi muss dagegen exakt aus demselben Farsi-Cue kopiert sein.
- Zitat "Du bringst mich noch ins Grab." -> wort_deutsch "jemanden ins Grab bringen", wortform_im_zitat "", luecken_segmente "bringst|ins Grab" (nicht "bringst mich noch ins Grab").
- Schlecht: wort_deutsch "Mal langsam!" bei Zitat "Mal langsam." (identisch bis auf Satzzeichen)."""
EDTECH_CSV_COLUMNS = (
    "Cue_ID", "Zeitstempel", "Farsi_Keyword", "Farsi_Hervorhebung", "German_Quote", "Deutsches_Wort",
    "Wortform_im_Zitat", "Lücken_Segmente",
    "Erklärung auf Farsi", "Erklärung im Kontext der Geschichte", "Register",
    "Semantik_Status", "Semantik_Hinweis", "Form_Status", "Form_Hinweis",
)

class Vokabel(BaseModel):
    cue_id: int
    german_quote: str
    wort_deutsch: str
    wortform_im_zitat: str
    luecken_segmente: str
    keyword_farsi: str
    highlight_farsi: str
    erklaerung_farsi: str
    erklaerung_kontext: str
    stilregister: str

class SemanticAlignment(BaseModel):
    item_id: int
    aligned: bool
    reason: str

class WordFormFix(BaseModel):
    item_id: int
    wortform_im_zitat: str
    luecken_segmente: str

def _fold_german(text):
    text = (text or '').replace('\u2019', "'").replace('\u2018', "'").replace('\u00b4', "'").replace('`', "'")
    return re.sub(r'\s+', ' ', text).strip().casefold()

MAX_FORM_WORDS = 4
INFOBOX_REGISTERS = {'norddeutsch', 'derb', 'gehoben', 'Jugendsprache'}
ALLOWED_REGISTERS = {
    'norddeutsch': 'norddeutsch', 'umgangssprachlich': 'umgangssprachlich', 'derb': 'derb',
    'jugendsprache': 'Jugendsprache', 'gehoben': 'gehoben',
}
SEPARABLE_PREFIXES = (
    'zurück', 'zusammen', 'weiter', 'heraus', 'hinein', 'herum', 'raus', 'rein', 'rum', 'runter', 'rauf',
    'herab', 'herauf', 'heran', 'hinaus', 'hinunter', 'hinzu', 'dazu', 'dabei', 'davon', 'vorbei',
    'fest', 'fort', 'frei', 'dicht', 'bereit', 'teil', 'statt', 'weg', 'los', 'hin', 'her', 'mit', 'nach',
    'vor', 'auf', 'aus', 'ab', 'an', 'ein', 'zu', 'um', 'durch', 'über', 'unter',
)
LEMMA_FILLER_WORDS = {
    'etwas', 'jemanden', 'jemandem', 'jemand', 'sich', 'mir', 'mich', 'ein', 'eine', 'einen', 'einem',
    'der', 'die', 'das', 'den', 'dem', 'des', 'zu',
}
_EDGE_PUNCTUATION = ' \t\u2026.!?,;:"\'\u201e\u201c\u201d\u00bb\u00ab'
_QUOTE_NOISE = ' \t#*\u266a\u266b\u2013\u2014-'

def clean_lemma(lemma):
    return (lemma or '').strip(_EDGE_PUNCTUATION)

def clean_quote(quote):
    return re.sub(r'\s+', ' ', (quote or '').strip(_QUOTE_NOISE)).strip()

def normalize_register(value):
    return ALLOWED_REGISTERS.get(_fold_german(value), '')

def _word_tokens(text):
    return re.findall(r"[\w']+", text or '')

def plausibility_issue(lemma, wortform, segments):
    """Erkennt zu schwache Wortformen: trennbares Verb oder Wendung nur durch ein Einzelwort abgedeckt."""
    if (segments or '').strip():
        return ''
    form_tokens = _word_tokens(wortform)
    if len(form_tokens) > MAX_FORM_WORDS:
        return f'Wortform hat {len(form_tokens)} Wörter; nur Kernbestandteile als Segmente verwenden (max. {MAX_FORM_WORDS}).'
    if len(form_tokens) != 1:
        return ''
    form = _fold_german(form_tokens[0])
    lemma_tokens = _word_tokens(clean_lemma(lemma))
    content = [t for t in lemma_tokens if t.casefold() not in LEMMA_FILLER_WORDS]
    if len(content) >= 2:
        return f'Wortform "{form_tokens[0]}" deckt die mehrteilige Wendung "{clean_lemma(lemma)}" nicht ab.'
    if not lemma_tokens or not lemma_tokens[-1][:1].islower():
        return ''
    verb = _fold_german(lemma_tokens[-1])
    prefix = next((p for p in SEPARABLE_PREFIXES if verb.startswith(p) and len(verb) > len(p) + 2), None)
    if prefix and (prefix not in form or len(form) <= len(prefix) + 1):
        return f'Trennbares Verb "{clean_lemma(lemma)}": Wortform "{form_tokens[0]}" enthält Präfix "{prefix}" nicht; Segmente verwenden.'
    return ''

def verify_word_form(quote, wortform, segments, lemma=''):
    """Prüft Wortform bzw. Lücken-Segmente gegen das Zitat.
    Status: OK, KEINE_LÜCKE (Zitat nicht lückentauglich), PRÜFEN (fehlerhaft)."""
    folded_quote = _fold_german(quote)
    parts = [_fold_german(part) for part in (segments or '').split('|') if part.strip()]
    form = _fold_german(wortform)
    if not parts and not form:
        if _normalized_quote(quote) == _normalized_quote(lemma) or len(folded_quote.split()) < 2:
            return 'KEINE_LÜCKE', 'Zitat ist (bis auf Satzzeichen) mit dem Wort identisch oder zu kurz.'
        return 'PRÜFEN', 'Weder Wortform noch Lücken-Segmente angegeben.'
    position = 0
    for part in (parts or [form]):
        match = re.compile(r'(?<!\w)' + re.escape(part) + r'(?!\w)').search(folded_quote, position)
        if not match:
            return 'PRÜFEN', f'"{part}" kommt nicht (in dieser Reihenfolge) im Zitat vor.'
        position = match.end()
    covered = ''.join(parts or [form])
    if _normalized_quote(covered).replace(' ', '') == _normalized_quote(quote).replace(' ', ''):
        if len(_word_tokens(quote)) > MAX_FORM_WORDS:
            return 'PRÜFEN', f'Wortform deckt das ganze Zitat ab ({len(_word_tokens(quote))} Wörter); nur Kernbestandteile als Segmente verwenden (max. {MAX_FORM_WORDS}).'
        return 'KEINE_LÜCKE', 'Wortform entspricht dem ganzen Zitat.'
    issue = plausibility_issue(lemma, wortform, segments)
    if issue:
        return 'PRÜFEN', issue
    return 'OK', ''

def normalize_persian(text):
    if not text:
        return ""
    text = text.replace('ي', 'ی').replace('ك', 'ک').replace('ۀ', 'ه').replace('ۃ', 'ه')
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def contains_persian_keyword(text, keyword):
    normalized_text = normalize_persian(text)
    normalized_keyword = normalize_persian(keyword)
    if not normalized_keyword:
        return False
    pattern = rf"(?<![\w\u200c]){re.escape(normalized_keyword)}(?![\w\u200c])"
    return re.search(pattern, normalized_text) is not None

def _read_srt(path):
    try:
        subs = pysrt.open(path, encoding='utf-8-sig')
    except UnicodeDecodeError:
        subs = pysrt.open(path, encoding='iso-8859-1')
    # pysrt lässt nicht-numerische Nummern (BOM, fehlend) als str/None stehen
    for position, sub in enumerate(subs, start=1):
        if not isinstance(sub.index, int):
            sub.index = position
    return subs

def _srt_start_time(subtitle):
    return f"{subtitle.start.hours:02d}:{subtitle.start.minutes:02d}:{subtitle.start.seconds:02d},{subtitle.start.milliseconds:03d}"

def paired_subtitle_cues(german_srt_path, farsi_srt_path):
    """Paart deutsche und persische Untertitel anhand ihrer SRT-Nummer."""
    german_subtitles = {sub.index: sub for sub in _read_srt(german_srt_path)}
    farsi_subtitles = {sub.index: sub for sub in _read_srt(farsi_srt_path)}
    return [
        {
            'cue_id': cue_id,
            'german_text': german_subtitles[cue_id].text,
            'farsi_text': farsi_subtitles[cue_id].text,
            'zeit': _srt_start_time(farsi_subtitles[cue_id]),
        }
        for cue_id in sorted(german_subtitles.keys() & farsi_subtitles.keys())
    ]

def _normalized_quote(text):
    return re.sub(r'[^\w\s]', '', (text or '').casefold()).strip()

def vocabulary_cue_candidates(row, cues):
    german_quote = _normalized_quote(row.get('German_Quote', row.get('german_quote', '')))
    farsi_keyword = row.get('Farsi_Keyword', row.get('keyword_farsi', '')).strip()
    if not german_quote or not farsi_keyword:
        return []
    return [
        cue['cue_id'] for cue in cues
        if german_quote in _normalized_quote(cue['german_text'])
        and contains_persian_keyword(cue['farsi_text'], farsi_keyword)
    ]

def canonicalize_vocabulary_cues(rows, cues):
    """Korrigiert eine Gemini-Cue-Zuordnung nur bei genau einem eindeutigen Paar."""
    cue_by_id = {cue['cue_id']: cue for cue in cues}
    for row in rows:
        candidates = vocabulary_cue_candidates(row, cues)
        if len(candidates) == 1:
            cue_id = candidates[0]
            row['cue_id'] = cue_id
            row['zeit'] = cue_by_id[cue_id]['zeit']
            if 'Cue_ID' in row:
                row['Cue_ID'] = cue_id
            if 'Zeitstempel' in row:
                row['Zeitstempel'] = cue_by_id[cue_id]['zeit']
    return rows

def validate_edtech_csv(german_srt_path, farsi_srt_path, csv_filepath):
    if not os.path.exists(csv_filepath) or not os.path.exists(farsi_srt_path):
        return {'rows': [], 'fieldnames': [], 'ts_mismatches': [], 'kw_mismatches': [], 'data_issues': []}

    farsi_subtitles = _read_srt(farsi_srt_path)
    farsi_by_id = {sub.index: sub for sub in farsi_subtitles}
    if german_srt_path and os.path.exists(german_srt_path):
        cues = paired_subtitle_cues(german_srt_path, farsi_srt_path)
    else:
        cues = [
            {'cue_id': sub.index, 'german_text': '', 'farsi_text': sub.text, 'zeit': _srt_start_time(sub)}
            for sub in farsi_subtitles
        ]

    rows = []
    with open(csv_filepath, 'r', encoding='utf-8-sig', newline='') as csv_file:
        reader = csv.DictReader(csv_file)
        fieldnames = reader.fieldnames or []
        rows.extend(reader)

    cue_by_id = {cue['cue_id']: cue for cue in cues}
    timestamp_mismatches = []
    keyword_mismatches = []
    data_issues = []
    seen_keywords = {}

    for row_index, row in enumerate(rows):
        keyword = (row.get('Farsi_Keyword') or '').strip()
        csv_time = (row.get('Zeitstempel') or '').strip()
        try:
            cue_id = int(row.get('Cue_ID', ''))
        except (TypeError, ValueError):
            cue_id = next((sub.index for sub in farsi_subtitles if _srt_start_time(sub) == csv_time), None)
            if cue_id is None:
                data_issues.append({'index': row_index, 'message': 'Cue_ID fehlt oder Zeitstempel kann keiner Untertitelnummer zugeordnet werden.'})
                keyword_mismatches.append({
                    'index': row_index, 'cue_id': None, 'keyword': keyword,
                    'csv_time': csv_time, 'srt_time': 'Cue_ID fehlt', 'other_cue_ids': []
                })
                continue

        normalized_keyword = normalize_persian(keyword)
        if normalized_keyword in seen_keywords:
            data_issues.append({
                'index': row_index,
                'message': f'Doppeltes Keyword wie CSV-Zeile {seen_keywords[normalized_keyword] + 1}: {keyword}'
            })
        else:
            seen_keywords[normalized_keyword] = row_index

        assigned_subtitle = farsi_by_id.get(cue_id)
        if assigned_subtitle is None:
            data_issues.append({'index': row_index, 'cue_id': cue_id, 'message': 'Cue_ID existiert nicht in der Farsi-SRT.'})
            keyword_mismatches.append({
                'index': row_index, 'cue_id': cue_id, 'keyword': keyword,
                'csv_time': csv_time, 'srt_time': 'Cue_ID nicht gefunden', 'other_cue_ids': []
            })
            continue

        if row.get('Semantik_Status') == 'PRÜFEN':
            data_issues.append({
                'index': row_index, 'cue_id': cue_id,
                'message': row.get('Semantik_Hinweis') or 'Semantische Zuordnung prüfen.'
            })

        if row.get('Form_Status') == 'PRÜFEN':
            data_issues.append({
                'index': row_index, 'cue_id': cue_id,
                'message': row.get('Form_Hinweis') or 'Wortform im Zitat prüfen.'
            })

        highlight_phrase = (
            (row.get('Farsi_Hervorhebung') or '').strip()
            if 'Farsi_Hervorhebung' in fieldnames
            else keyword
        )
        if highlight_phrase and contains_persian_keyword(assigned_subtitle.text, highlight_phrase):
            actual_time = _srt_start_time(assigned_subtitle)
            if csv_time != actual_time:
                timestamp_mismatches.append({
                    'index': row_index, 'cue_id': cue_id, 'keyword': highlight_phrase,
                    'csv_time': csv_time, 'srt_time': actual_time, 'other_cue_ids': []
                })
            continue

        checked_phrase = (
            highlight_phrase if 'Farsi_Hervorhebung' in fieldnames else keyword
        )
        neighboring_ids = [cue_id - 1, cue_id + 1]
        other_cue_ids = [
            neighbor_id for neighbor_id in neighboring_ids
            if neighbor_id in farsi_by_id and contains_persian_keyword(farsi_by_id[neighbor_id].text, checked_phrase)
        ]
        keyword_mismatches.append({
            'index': row_index, 'cue_id': cue_id, 'keyword': checked_phrase or '(Feld leer)',
            'field': 'Farsi_Hervorhebung' if 'Farsi_Hervorhebung' in fieldnames else 'Farsi_Keyword',
            'csv_time': csv_time,
            'srt_time': _srt_start_time(farsi_by_id[other_cue_ids[0]]) if other_cue_ids else 'Nicht im Cue oder direkten Nachbar-Cues gefunden',
            'other_cue_ids': other_cue_ids,
        })

    return {
        'rows': rows,
        'fieldnames': fieldnames,
        'ts_mismatches': timestamp_mismatches,
        'kw_mismatches': keyword_mismatches,
        'data_issues': data_issues,
    }

def validate_csv_timestamps(farsi_srt_path, csv_filepath):
    report = validate_edtech_csv(None, farsi_srt_path, csv_filepath)
    return report['rows'], report['ts_mismatches'], report['kw_mismatches'], report['fieldnames']

def fix_csv_timestamps(csv_filepath, rows, fieldnames, timestamp_mismatches):
    for match in timestamp_mismatches:
        rows[match['index']]['Zeitstempel'] = match['srt_time']
        if 'Cue_ID' in rows[match['index']] and match.get('cue_id') is not None:
            rows[match['index']]['Cue_ID'] = match['cue_id']
        
    with open(csv_filepath, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)
    return True

def validate_ass_content(ass_filepath):
    if not os.path.exists(ass_filepath):
        return ['ASS-Datei wurde nicht erstellt.']
    with open(ass_filepath, 'r', encoding='utf-8') as ass_file:
        content = ass_file.read()
    issues = []
    if '[Events]' not in content or 'Dialogue:' not in content:
        issues.append('ASS-Datei enthält keine Untertitelereignisse.')
    return issues

def gemini_followup_fix_mismatches(
    api_key, farsi_srt_path, csv_filepath, mismatches,
    german_srt_path=None, model='gemini-3.1-flash-lite'
):
    if not mismatches:
        return True
        
    client = genai.Client(api_key=api_key)
    with open(csv_filepath, 'r', encoding='utf-8-sig') as f:
        current_csv = f.read()

    farsi_subtitles = _read_srt(farsi_srt_path)
    if german_srt_path and os.path.exists(german_srt_path):
        paired_cues = paired_subtitle_cues(german_srt_path, farsi_srt_path)
        cue_lookup = {cue['cue_id']: cue for cue in paired_cues}
    else:
        cue_lookup = {
            subtitle.index: {
                'cue_id': subtitle.index,
                'german_text': '',
                'farsi_text': subtitle.text,
                'zeit': _srt_start_time(subtitle),
            }
            for subtitle in farsi_subtitles
        }
    local_cues = {}
    for mismatch in mismatches:
        cue_id = mismatch.get('cue_id')
        if cue_id is None:
            continue
        for local_id in (cue_id - 1, cue_id, cue_id + 1):
            if local_id in cue_lookup:
                local_cues[local_id] = cue_lookup[local_id]
    prompt = f"""Du bist ein präziser Daten-Analyst für Untertitel.
Korrigiere ausschließlich markierte CSV-Zeilen. Wenn field=Farsi_Hervorhebung, ändere nur dieses Feld: Es muss exakt aus dem Farsi-Text des zugewiesenen Cue_ID oder seiner direkten Nachbar-Cues kopiert werden. Lass Farsi_Keyword unverändert; es ist die sinngemäße Bedeutung und muss nicht wörtlich im Untertitel stehen.
Ändere Cue_ID nur dann, wenn eine eindeutige lokale Zuordnung nachweisbar ist. Erfinde oder verschiebe keine Untertitelnummern.
Zeitstempel müssen exakt zum Start des tatsächlich zugewiesenen Cue passen. Gib die vollständige CSV mit allen Originalspalten aus.

ABWEICHUNGEN: {json.dumps(mismatches, ensure_ascii=False)}
LOKALE CUE-KONTEXTE (nur n-1, n, n+1): {json.dumps(local_cues, ensure_ascii=False)}
AKTUELLE CSV: {current_csv}

REGELN:
- Gib AUSSCHLIESSLICH die rohen CSV-Daten aus. Kein Markdown, kein Begrüßungstext.
- Umschließe JEDES Feld zwingend mit doppelten Anführungszeichen ("...").
- Bewahre unveränderte Zeilen, Spalten und Werte exakt.
"""
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.1)
    )
    
    fixed_csv_data = response.text.replace('```csv', '').replace('```', '').strip()
    temporary_csv = f'{csv_filepath}.tmp'
    try:
        with open(temporary_csv, 'w', encoding='utf-8-sig', newline='') as csv_file:
            csv_file.write(fixed_csv_data)
        os.replace(temporary_csv, csv_filepath)
    finally:
        if os.path.exists(temporary_csv):
            os.remove(temporary_csv)
    return True

def _log_usage(label, response):
    usage = getattr(response, 'usage_metadata', None)
    if usage:
        logger.info(
            'EdTech-%s: Eingabe-Tokens=%s, Ausgabe-Tokens=%s, Gesamt=%s',
            label, usage.prompt_token_count, usage.candidates_token_count, usage.total_token_count
        )

def _clean_vocabulary(vokabeln):
    for vocabulary in vokabeln:
        vocabulary['wort_deutsch'] = clean_lemma(vocabulary.get('wort_deutsch', ''))
        vocabulary['german_quote'] = clean_quote(vocabulary.get('german_quote', ''))
        vocabulary['wortform_im_zitat'] = (vocabulary.get('wortform_im_zitat') or '').strip()
        vocabulary['stilregister'] = normalize_register(vocabulary.get('stilregister', ''))
    return vokabeln

def _flag_duplicate_lemmas(vokabeln):
    seen = {}
    for vocabulary in vokabeln:
        key = _fold_german(vocabulary.get('wort_deutsch', ''))
        if key in seen and not vocabulary.get('form_hinweis'):
            vocabulary['form_hinweis'] = f'Lemma doppelt (wie Cue {seen[key]}).'
        seen.setdefault(key, vocabulary.get('cue_id'))

def _apply_form_status(vocabulary):
    status, hint = verify_word_form(
        vocabulary.get('german_quote', ''), vocabulary.get('wortform_im_zitat', ''),
        vocabulary.get('luecken_segmente', ''), vocabulary.get('wort_deutsch', '')
    )
    vocabulary['form_status'] = status
    vocabulary['form_hinweis'] = hint
    return status

def _verify_and_fix_word_forms(client, model, vokabeln, cues):
    """Verifiziert Wortformen per Code und korrigiert Fehler gezielt in einem Zusatzaufruf."""
    failed = [index for index, vocabulary in enumerate(vokabeln) if _apply_form_status(vocabulary) == 'PRÜFEN']
    if not failed or client is None:
        return vokabeln
    cue_by_id = {cue['cue_id']: cue for cue in cues}
    entries = []
    for index in failed:
        vocabulary = vokabeln[index]
        cue = cue_by_id.get(int(vocabulary['cue_id']), {})
        entries.append({
            'item_id': index + 1,
            'german_quote': vocabulary['german_quote'],
            'wort_deutsch': vocabulary['wort_deutsch'],
            'wortform_im_zitat': vocabulary.get('wortform_im_zitat', ''),
            'luecken_segmente': vocabulary.get('luecken_segmente', ''),
            'problem': vocabulary['form_hinweis'],
            'cue_deutsch': cue.get('german_text', ''),
        })
    prompt = f"""Korrigiere für jeden Eintrag nur die Felder wortform_im_zitat und luecken_segmente.
wortform_im_zitat muss eine zusammenhängende, zeichengenaue Teilzeichenkette von german_quote sein (gebeugte Form des Worts, nicht der ganze Satz).
Die Wortform hat höchstens 4 Wörter; bei längeren Wendungen nur die Kernbestandteile als Segmente ohne Füllwörter (mir, mich, nicht, wieder, noch, da, ...), z.B. "frier|den Arsch ab".
Bei getrennten Teilen (z.B. trennbare Verben) wortform_im_zitat leer lassen und luecken_segmente als zeichengenaue Teile in Zitat-Reihenfolge mit "|" trennen, z.B. "hau|ab".
Gib genau ein Ergebnis je item_id zurück.

EINTRÄGE:
{json.dumps(entries, ensure_ascii=False)}"""
    try:
        response = client.models.generate_content(
            model=model, contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0,
                response_schema=list[WordFormFix],
                thinking_config=types.ThinkingConfig(thinking_budget=0)
            )
        )
        _log_usage('Wortform-Korrektur', response)
        fixes = [item.model_dump() for item in response.parsed] if response.parsed else json.loads(response.text)
    except Exception as error:
        logger.warning('EdTech-Wortform-Korrektur fehlgeschlagen: %s', error)
        return vokabeln
    for fix in fixes:
        index = int(fix['item_id']) - 1
        if index in failed:
            vokabeln[index]['wortform_im_zitat'] = fix.get('wortform_im_zitat', '')
            vokabeln[index]['luecken_segmente'] = fix.get('luecken_segmente', '')
            _apply_form_status(vokabeln[index])
    return vokabeln

def generate_learning_subtitles(
    farsi_srt_path, ass_filepath, summary="", api_key=None, german_srt_path=None, 
    csv_filepath=None, generate_csv_only=False, custom_system_instruction=None,
    force_csv_regeneration=False,
    infobox_duration=7, highlight_bold=False, highlight_underline=True,
    highlight_color=False, infobox_content="german_only", sync_offset_ms=0,
    model="gemini-3.1-flash-lite"
):
    if not csv_filepath:
        csv_filepath = farsi_srt_path.replace("_FA.srt", "_Vokabeln.csv")

    # PHASE 1: CSV Einlesen oder neu von Gemini generieren lassen
    if os.path.exists(csv_filepath) and not force_csv_regeneration:
        pass # Wir lesen sie später sauber mit csv.DictReader ein
    elif german_srt_path and api_key:
        client = genai.Client(api_key=api_key)
        
        try:
            with open(german_srt_path, 'r', encoding='utf-8') as f: de_srt = f.read()
        except UnicodeDecodeError:
            with open(german_srt_path, 'r', encoding='iso-8859-1') as f: de_srt = f.read()

        try:
            with open(farsi_srt_path, 'r', encoding='utf-8') as f: fa_srt = f.read()
        except UnicodeDecodeError:
            with open(farsi_srt_path, 'r', encoding='iso-8859-1') as f: fa_srt = f.read()
                
        base_instruction = append_episode_summary(
            custom_system_instruction or "Du bist ein erfahrener Sprachdozent für Deutsch als Fremdsprache (B2/C1)...",
            summary
        )
        cues = paired_subtitle_cues(german_srt_path, farsi_srt_path)
        if not cues:
            raise ValueError('Deutsche und persische SRT enthalten keine gemeinsam nummerierten Untertitel.')

        cue_reference = '\n'.join(
            f"Cue_ID: {cue['cue_id']} | Zeitstempel: {cue['zeit']} | Deutsch: {cue['german_text']} | Farsi: {cue['farsi_text']}"
            for cue in cues
        )
        prompt = f"""{base_instruction}
{EDTECH_GENERATION_INSTRUCTIONS}

ZUSAMMENFASSUNG:
{summary or 'Keine Episodenzusammenfassung angegeben.'}

GEPaarte UNTERTITEL-CUES:
{cue_reference}"""
        
        config = types.GenerateContentConfig(
            system_instruction=base_instruction,
            temperature=0.3,
            response_schema=list[Vokabel],
            thinking_config=types.ThinkingConfig(thinking_budget=0)
        )

        response = client.models.generate_content(
            model=model, contents=prompt, config=config
        )
        
        _log_usage('Generierung', response)
        if response.parsed:
            vokabeln_raw = [v.model_dump() for v in response.parsed]
        else:
            vokabeln_raw = json.loads(response.text)
            
        canonicalize_vocabulary_cues(vokabeln_raw, cues)
        _clean_vocabulary(vokabeln_raw)
        _verify_and_fix_word_forms(client, model, vokabeln_raw, cues)
        _flag_duplicate_lemmas(vokabeln_raw)
        semantic_entries = [
            {'item_id': item_id, **vocabulary}
            for item_id, vocabulary in enumerate(vokabeln_raw, start=1)
        ]
        semantic_prompt = f"""Prüfe für jeden Vokabeleintrag, ob deutsches Zitat und Farsi-Keyword semantisch zusammenpassen.
Beurteile die Zuordnung zur angegebenen Cue_ID anhand des folgenden Deutschen und Persischen.
Gib für jede übergebene item_id genau ein Ergebnis mit derselben item_id, aligned (true/false) und bei false einem kurzen Grund aus.

EINTRÄGE:
{json.dumps(semantic_entries, ensure_ascii=False)}

GEPaarte CUES:
{cue_reference}"""
        semantic_response = client.models.generate_content(
            model=model,
            contents=semantic_prompt,
            config=types.GenerateContentConfig(
                temperature=0,
                response_schema=list[SemanticAlignment],
                thinking_config=types.ThinkingConfig(thinking_budget=0)
            )
        )
        _log_usage('Semantik-Prüfung', semantic_response)
        if semantic_response.parsed:
            semantic_results = [item.model_dump() for item in semantic_response.parsed]
        else:
            semantic_results = json.loads(semantic_response.text)
        semantic_by_id = {int(item['item_id']): item for item in semantic_results}
        cue_by_id = {cue['cue_id']: cue for cue in cues}
        csv_rows = []
        for item_id, vocabulary in enumerate(vokabeln_raw, start=1):
            semantic = semantic_by_id.get(item_id, {'aligned': False, 'reason': 'Keine semantische Prüfung erhalten.'})
            cue = cue_by_id.get(int(vocabulary['cue_id']))
            if not cue:
                semantic = {'aligned': False, 'reason': 'Cue_ID ist in den gepaarten SRTs nicht vorhanden.'}
                cue_id = int(vocabulary['cue_id'])
                cue_time = ''
            else:
                cue_id = cue['cue_id']
                cue_time = cue['zeit']
            csv_rows.append({
                'Cue_ID': cue_id,
                'Zeitstempel': cue_time,
                'Farsi_Keyword': vocabulary['keyword_farsi'],
                'Farsi_Hervorhebung': vocabulary.get('highlight_farsi', ''),
                'German_Quote': vocabulary['german_quote'],
                'Deutsches_Wort': vocabulary['wort_deutsch'],
                'Wortform_im_Zitat': vocabulary.get('wortform_im_zitat', ''),
                'Lücken_Segmente': vocabulary.get('luecken_segmente', ''),
                'Erklärung auf Farsi': vocabulary['erklaerung_farsi'],
                'Erklärung im Kontext der Geschichte': vocabulary.get('erklaerung_kontext', ''),
                'Register': vocabulary.get("stilregister", ""),
                'Semantik_Status': 'OK' if semantic.get('aligned') else 'PRÜFEN',
                'Semantik_Hinweis': semantic.get('reason', '') if not semantic.get('aligned') else '',
                'Form_Status': vocabulary.get('form_status', ''),
                'Form_Hinweis': vocabulary.get('form_hinweis', ''),
            })

        csv_fields = list(EDTECH_CSV_COLUMNS)
        temporary_csv = f'{csv_filepath}.tmp'
        try:
            with open(temporary_csv, 'w', encoding='utf-8-sig', newline='') as csv_file:
                writer = csv.DictWriter(csv_file, fieldnames=csv_fields, quoting=csv.QUOTE_ALL)
                writer.writeheader()
                writer.writerows(csv_rows)
            os.replace(temporary_csv, csv_filepath)
        finally:
            if os.path.exists(temporary_csv):
                os.remove(temporary_csv)
    else:
        raise ValueError("Weder eine gültige CSV-Datei noch API-Zugangsdaten für die Neuerstellung gefunden.")

    if generate_csv_only:
        return None, csv_filepath

    # PHASE 2: ASS GENERIERUNG
    try:
        with open(farsi_srt_path, 'r', encoding='utf-8') as f:
            fa_srt = f.read()
    except UnicodeDecodeError:
        with open(farsi_srt_path, 'r', encoding='iso-8859-1') as f:
            fa_srt = f.read()

    ass_header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Standard,Arial,50,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,10,10,50,1
Style: InfoBox,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,3,8,1,9,50,50,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    vokabeln = []
    seen_vocabulary = set()
    with open(csv_filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            vokabel = {
                'cue_id': int(row['Cue_ID']) if row.get('Cue_ID', '').strip().isdigit() else None,
                'zeit': row['Zeitstempel'].strip(), 
                'keyword_farsi': row['Farsi_Keyword'].strip(),
                'highlight_farsi': (
                    (row.get('Farsi_Hervorhebung') or '').strip()
                    if 'Farsi_Hervorhebung' in (reader.fieldnames or [])
                    else row['Farsi_Keyword'].strip()
                ),
                'wort_deutsch': row['Deutsches_Wort'].strip(),
                'erklaerung_farsi': row['Erklärung auf Farsi'].strip(),
                'erklaerung_kontext': row['Erklärung im Kontext der Geschichte'].strip(),
                'register': (row.get('Register') or '').strip(),
            }
            vocabulary_key = (vokabel['zeit'], normalize_persian(vokabel['keyword_farsi']))
            if not vocabulary_key[1] or vocabulary_key in seen_vocabulary:
                continue
            seen_vocabulary.add(vocabulary_key)
            vokabeln.append(vokabel)

    blocks = re.split(r'\n\s*\n', fa_srt.strip())
    ass_events = []
    
    color_map = {
        'white': '&HFFFFFF&', 'yellow': '&H00FFFF&', 'cyan': '&HFFFF00&',
        'green': '&H00FF00&', 'blue': '&HFF0000&', 'red': '&H0000FF&'
    }

    def convert_html_to_ass(text):
        def repl(match):
            color = match.group(1).strip()
            if color.startswith('#') and len(color) == 7:
                r = color[1:3]
                g = color[3:5]
                b = color[5:7]
                return f"{{\\c&H{b}{g}{r}&}}"
            else:
                return f"{{\\c{color_map.get(color.lower(), '&HFFFFFF&')}}}"
        text = re.sub(r'<font color="([^"]+)">', repl, text)
        return text.replace('</font>', '{\\c}')

    def srt_time_to_ass(t):
        h, m, s_ms = t.split(':')
        s, ms = s_ms.split(',')
        dt = datetime(2000, 1, 1, int(h), int(m), int(s), int(ms)*1000)
        dt_shifted = dt + timedelta(milliseconds=sync_offset_ms)
        return f"{dt_shifted.hour}:{dt_shifted.minute:02d}:{dt_shifted.second:02d}.{dt_shifted.microsecond // 10000:02d}"

    for block in blocks:
        lines = block.split('\n')
        if len(lines) < 3 or '-->' not in lines[1]: continue
        try:
            subtitle_cue_id = int(lines[0].strip())
        except ValueError:
            subtitle_cue_id = None
            
        start_srt, end_srt = lines[1].split(' --> ')
        start_ass = srt_time_to_ass(start_srt.strip())
        end_ass = srt_time_to_ass(end_srt.strip())
        
        text_farsi = r'\N'.join(lines[2:])
        text_farsi = convert_html_to_ass(text_farsi)
        
        for vokabel in vokabeln:
            cue_matches = vokabel['cue_id'] is not None and vokabel['cue_id'] == subtitle_cue_id
            legacy_time_matches = vokabel['cue_id'] is None and vokabel['zeit'] in start_srt
            if cue_matches or legacy_time_matches:
                open_tags, close_tags = [], []
                
                if highlight_bold:
                    open_tags.append(r"\b1"); close_tags.append(r"\b0")
                if highlight_underline:
                    open_tags.append(r"\u1"); close_tags.append(r"\u0")
                if highlight_color:
                    open_tags.append(r"\c&H00FFFF&"); close_tags.append(r"\c")
                
                if open_tags:
                    tag_string = "".join(open_tags).replace('\\', '\\\\')
                    close_string = "".join(close_tags).replace('\\', '\\\\')
                    highlight_tag = rf"\\N{{{tag_string}}}\1{{{close_string}}}\\N"
                else:
                    highlight_tag = r"\1"
                    
                highlight_phrase = vokabel['highlight_farsi']
                source_farsi = '\n'.join(lines[2:])
                if highlight_phrase and contains_persian_keyword(source_farsi, highlight_phrase):
                    regex_pattern = re.escape(highlight_phrase).replace(r'\ ', r'(?:\s+|\\N)')
                    highlight_pattern = re.compile(
                        rf"(?:(?<=\\N)|(?<![\w\u200c]))({regex_pattern})(?![\w\u200c])"
                    )
                    text_farsi = highlight_pattern.sub(highlight_tag, text_farsi)
                               
                lemma_text = f"{{\\b1}}{vokabel['wort_deutsch']}{{\\b0}}"
                if vokabel['register'] in INFOBOX_REGISTERS:
                    lemma_text += f" {{\\fs32\\c&HC0C0C0&}}({vokabel['register']}){{\\r}}"
                if infobox_content == "german_and_farsi_keyword":
                    box_text = f"{lemma_text}\\N{{\\c&H00FFFF&}}{vokabel['keyword_farsi']}{{\\c}}"
                elif infobox_content == "german_and_farsi_explanation":
                    box_text = f"{lemma_text}\\N{{\\c&H00FFFF&}}{vokabel['erklaerung_farsi']}{{\\c}}"
                else:
                    box_text = lemma_text
                
                h, m, s_ms = start_srt.strip().split(':')
                s, ms = s_ms.split(',')
                t_base = datetime(2000, 1, 1, int(h), int(m), int(s), int(ms)*1000) + timedelta(milliseconds=sync_offset_ms)
                t_end = t_base + timedelta(seconds=infobox_duration)
                
                box_start = f"{t_base.hour}:{t_base.minute:02d}:{t_base.second:02d}.{t_base.microsecond // 10000:02d}"
                box_end = f"{t_end.hour}:{t_end.minute:02d}:{t_end.second:02d}.{t_end.microsecond // 10000:02d}"
                
                ass_events.append(f"Dialogue: 1,{box_start},{box_end},InfoBox,,0,0,0,,{box_text}")
                
        text_farsi = re.sub(r"(?:\s*\\N\s*)+", r"\\N", text_farsi)
        text_farsi = re.sub(r"^\\N|\\N$", "", text_farsi)
        
        wrapped_lines = []
        for line in text_farsi.split(r"\N"):
            line = line.strip()
            if not line or line in {",", "،"}:
                continue
            wrapped_lines.append(f"\u202B{line}\u202C")
        text_farsi = r"\N".join(wrapped_lines)
        
        ass_events.append(f"Dialogue: 0,{start_ass},{end_ass},Standard,,0,0,0,,{text_farsi}")
        
    temporary_ass = f'{ass_filepath}.tmp'
    try:
        with open(temporary_ass, 'w', encoding='utf-8') as ass_file:
            ass_file.write(ass_header + '\n'.join(ass_events))
        validation_issues = validate_ass_content(temporary_ass)
        if validation_issues:
            raise ValueError(f"ASS-Prüfung fehlgeschlagen: {'; '.join(validation_issues)}")
        os.replace(temporary_ass, ass_filepath)
    finally:
        if os.path.exists(temporary_ass):
            os.remove(temporary_ass)
        
    return ass_filepath, csv_filepath