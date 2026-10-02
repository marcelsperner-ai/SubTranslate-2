import os
import re
import csv
import json
from io import StringIO
from datetime import datetime, timedelta
from google import genai
from google.genai import types
import pysrt
from pydantic import BaseModel
from app.prompt_manager import append_episode_summary

class Vokabel(BaseModel):
    cue_id: int
    german_quote: str
    wort_deutsch: str
    keyword_farsi: str
    erklaerung_farsi: str
    erklaerung_kontext: str

class SemanticAlignment(BaseModel):
    item_id: int
    aligned: bool
    reason: str

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
        return pysrt.open(path, encoding='utf-8')
    except UnicodeDecodeError:
        return pysrt.open(path, encoding='iso-8859-1')

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

        if contains_persian_keyword(assigned_subtitle.text, keyword):
            actual_time = _srt_start_time(assigned_subtitle)
            if csv_time != actual_time:
                timestamp_mismatches.append({
                    'index': row_index, 'cue_id': cue_id, 'keyword': keyword,
                    'csv_time': csv_time, 'srt_time': actual_time, 'other_cue_ids': []
                })
            continue

        neighboring_ids = [cue_id - 1, cue_id + 1]
        other_cue_ids = [
            neighbor_id for neighbor_id in neighboring_ids
            if neighbor_id in farsi_by_id and contains_persian_keyword(farsi_by_id[neighbor_id].text, keyword)
        ]
        keyword_mismatches.append({
            'index': row_index, 'cue_id': cue_id, 'keyword': keyword,
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
Korrigiere ausschließlich markierte CSV-Zeilen. Ein Farsi_Keyword darf nur im zugewiesenen Cue_ID oder seinen direkten Nachbar-Cues vorkommen.
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
Erstelle 25 bis 35 Vokabeleinträge aus den exakt gepaarten Untertiteln.
Für jeden Eintrag gib folgende Felder zurück:
1. "cue_id": die Nummer des Untertitels, aus dem das deutsche Wort und Farsi-Keyword stammen.
2. "german_quote": ein eindeutiges, wortgetreues deutsches Zitat aus genau diesem Untertitel.
3. "wort_deutsch": das deutsche Wort.
4. "keyword_farsi": MUSS zu 100 % zeichengenau aus dem Farsi-Text desselben Cue kopiert werden.
5. "erklaerung_farsi": Bedeutung auf Farsi.
6. "erklaerung_kontext": kurzer deutscher Satz zur Handlung.
Wähle keine Wörter, deren deutsche und persische Stelle nicht eindeutig demselben Cue zugeordnet werden können.

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
        
        if response.parsed:
            vokabeln_raw = [v.model_dump() for v in response.parsed]
        else:
            vokabeln_raw = json.loads(response.text)
            
        canonicalize_vocabulary_cues(vokabeln_raw, cues)
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
                'German_Quote': vocabulary['german_quote'],
                'Deutsches_Wort': vocabulary['wort_deutsch'],
                'Erklärung auf Farsi': vocabulary['erklaerung_farsi'],
                'Erklärung im Kontext der Geschichte': vocabulary.get('erklaerung_kontext', ''),
                'Semantik_Status': 'OK' if semantic.get('aligned') else 'PRÜFEN',
                'Semantik_Hinweis': semantic.get('reason', '') if not semantic.get('aligned') else '',
            })

        csv_fields = [
            'Cue_ID', 'Zeitstempel', 'Farsi_Keyword', 'German_Quote', 'Deutsches_Wort',
            'Erklärung auf Farsi', 'Erklärung im Kontext der Geschichte',
            'Semantik_Status', 'Semantik_Hinweis',
        ]
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
                'wort_deutsch': row['Deutsches_Wort'].strip(),
                'erklaerung_farsi': row['Erklärung auf Farsi'].strip(),
                'erklaerung_kontext': row['Erklärung im Kontext der Geschichte'].strip()
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
                    
                regex_pattern = re.escape(vokabel['keyword_farsi']).replace(r'\ ', r'(?:\s+|\\N)')
                keyword_pattern = re.compile(
                    rf"(?:(?<=\\N)|(?<![\w\u200c]))({regex_pattern})(?![\w\u200c])"
                )
                text_farsi = keyword_pattern.sub(highlight_tag, text_farsi)
                               
                if infobox_content == "german_and_farsi_keyword":
                    box_text = f"{{\\b1}}{vokabel['wort_deutsch']}{{\\b0}}\\N{{\\c&H00FFFF&}}{vokabel['keyword_farsi']}{{\\c}}"
                elif infobox_content == "german_and_farsi_explanation":
                    box_text = f"{{\\b1}}{vokabel['wort_deutsch']}{{\\b0}}\\N{{\\c&H00FFFF&}}{vokabel['erklaerung_farsi']}{{\\c}}"
                else:
                    box_text = f"{{\\b1}}{vokabel['wort_deutsch']}{{\\b0}}"
                
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