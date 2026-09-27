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

class Vokabel(BaseModel):
    zeit: str
    wort_deutsch: str
    keyword_farsi: str
    erklaerung_farsi: str
    erklaerung_kontext: str  # <-- Neues Feld für den Kontext hinzugefügt

def normalize_persian(text):
    """Normalisiert persischen Text für den robusten Abgleich."""
    if not text:
        return ""
    text = text.replace('ي', 'ی').replace('ك', 'ک').replace('ۀ', 'ه').replace('ۃ', 'ه')
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text
def validate_csv_timestamps(farsi_srt_path, csv_filepath):
    """
    Prüft die Farsi-Keywords in der CSV gegen die SRT.
    Gibt rows, timestamp_mismatches (korrigierbar per Python), keyword_mismatches (für Gemini) und fieldnames zurück.
    """
    if not os.path.exists(csv_filepath) or not os.path.exists(farsi_srt_path):
        return [], [], [], []

    subs = pysrt.open(farsi_srt_path, encoding='utf-8')
    
    rows = []
    with open(csv_filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            rows.append(row)
            
    timestamp_mismatches = []
    keyword_mismatches = []
    
    for idx, row in enumerate(rows):
        keyword = row['Farsi_Keyword'].strip()
        norm_keyword = normalize_persian(keyword)
        csv_time = row['Zeitstempel'].strip()
        
        exact_match_found = False
        fuzzy_match_time = None
        
        for sub in subs:
            s_time = f"{sub.start.hours:02d}:{sub.start.minutes:02d}:{sub.start.seconds:02d},{sub.start.milliseconds:03d}"
            norm_sub_text = normalize_persian(sub.text)
            
            # Exakter Check
            if keyword in sub.text:
                if s_time == csv_time:
                    exact_match_found = True
                    break
                elif not fuzzy_match_time:
                    fuzzy_match_time = s_time
            # Normalisierter Fuzzy-Check
            elif norm_keyword and norm_keyword in norm_sub_text:
                # NEU: Auch hier prüfen, ob der Zeitstempel exakt passt!
                if s_time == csv_time:
                    exact_match_found = True
                    break
                elif not fuzzy_match_time:
                    fuzzy_match_time = s_time
                    
        if exact_match_found:
            continue
            
        if fuzzy_match_time:
            # Keyword gefunden, aber Zeitstempel weicht ab
            timestamp_mismatches.append({
                'index': idx,
                'keyword': keyword,
                'csv_time': csv_time,
                'srt_time': fuzzy_match_time
            })
        else:
            # Keyword gar nicht gefunden
            keyword_mismatches.append({
                'index': idx,
                'keyword': keyword,
                'csv_time': csv_time,
                'srt_time': "Nicht gefunden in SRT"
            })
            
    return rows, timestamp_mismatches, keyword_mismatches, fieldnames

def fix_csv_timestamps(csv_filepath, rows, fieldnames, timestamp_mismatches):
    """Übernimmt die von Python gefundenen SRT-Zeitstempel in die CSV (Option 2)."""
    for match in timestamp_mismatches:
        rows[match['index']]['Zeitstempel'] = match['srt_time']
        
    with open(csv_filepath, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)
    return csv_filepath

def gemini_followup_fix_mismatches(api_key, farsi_srt_path, csv_filepath, mismatches):
    """Sendet verbleibende nicht gefundene Keywords an Gemini Pro zur Korrektur."""
    if not mismatches:
        return csv_filepath
        
    client = genai.Client(api_key=api_key)
    
    with open(farsi_srt_path, 'r', encoding='utf-8') as f:
        fa_srt = f.read()
        
    with open(csv_filepath, 'r', encoding='utf-8-sig') as f:
        current_csv = f.read()

    mismatch_keywords = [m['keyword'] for m in mismatches]

    prompt = f"""Du bist ein präziser Daten-Analyst für Untertitel.
Ich habe eine Vokabel-CSV, bei der einige "Farsi_Keyword"-Einträge in der persischen SRT-Datei so nicht exakt gefunden wurden.

DEINE AUFGABE:
Korrigiere NUR die fehlerhaften Keywords oder passe deren Zeitstempel so an, dass das "Farsi_Keyword" zu 100% zeichengenau aus der unten stehenden persischen SRT kopiert wird. Gib die vollständige korrigierte CSV aus.

FEHLERHAFTE KEYWORDS:
{mismatch_keywords}

PERSISCHE SRT:
{fa_srt}

AKTUELLE CSV:
{current_csv}

REGELN:
- Gib AUSSCHLIESSLICH die rohen CSV-Daten aus. Kein Markdown, kein Begrüßungstext.
- Umschließe JEDES Feld zwingend mit doppelten Anführungszeichen ("...").
"""

    response = client.models.generate_content(
        model="gemini-3.1-pro-preview", 
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.1)
    )
    
    fixed_csv_data = response.text.replace('```csv', '').replace('```', '').strip()
    with open(csv_filepath, 'w', encoding='utf-8-sig') as f:
        f.write(fixed_csv_data)
        
    return csv_filepath

def generate_learning_subtitles(
    farsi_srt_path, 
    ass_filepath, 
    summary="", 
    api_key=None, 
    german_srt_path=None, 
    csv_filepath=None,
    generate_csv_only=False,
    custom_system_instruction=None,
    infobox_duration=7,
    highlight_bold=False,
    highlight_underline=True,
    highlight_color=False,
    infobox_content="german_only",
    sync_offset_ms=0
):
    # --- AUTOMATISCHER FALLBACK FÜR DEN PFAD ---
    if not csv_filepath:
        csv_filepath = farsi_srt_path.replace("_FA.srt", "_Vokabeln.csv")

    if os.path.exists(csv_filepath):
        with open(csv_filepath, 'r', encoding='utf-8-sig') as f:
            csv_data = f.read()
    elif german_srt_path and api_key and summary:
        client = genai.Client(api_key=api_key)
        
        try:
            with open(german_srt_path, 'r', encoding='utf-8') as f:
                de_srt = f.read()
        except UnicodeDecodeError:
            with open(german_srt_path, 'r', encoding='iso-8859-1') as f:
                de_srt = f.read()

        try:
            with open(farsi_srt_path, 'r', encoding='utf-8') as f:
                fa_srt = f.read()
        except UnicodeDecodeError:
            with open(farsi_srt_path, 'r', encoding='iso-8859-1') as f:
                fa_srt = f.read()
                
        base_instruction = custom_system_instruction if custom_system_instruction else "Du bist ein erfahrener Sprachdozent für Deutsch als Fremdsprache (B2/C1)..."       

        prompt = f"""{base_instruction}

SPALTEN DER CSV-DATEI UND REGELN:
1. "Zeitstempel": Nimm EXAKT und AUSSCHLIESSLICH den Start-Zeitstempel des SRT-Blocks (der Wert links vom '-->'). 
   VERBOTEN: Verwende niemals den End-Zeitstempel (rechts vom '-->') und niemals den Zeitstempel des vorherigen Blocks!
2. "Farsi_Keyword": **KRITISCH!** Dieses Wort oder diese Phrase MUSS zu 100 % zeichengenau so aus dem Text der persischen SRT-Datei kopiert werden.
3. "Deutsches_Wort": Das entsprechende deutsche Wort (Infinitiv bei Verben, Nominativ Singular bei Nomen).
4. "Erklärung auf Farsi": Eine kurze, präzise Erklärung der Bedeutung auf Farsi.
5. "Erklärung im Kontext der Geschichte": Ein kurzer deutscher Satz (1-2 Sätze) mit Bezug zur Handlung.

BEISPIEL FÜR KORREKTE EXTRAKTION:
SRT-Block:
45
00:02:50,400 --> 00:02:52,000
<font color="#00FFFF">اینجا هم همیشه همون جوّ حاکمه</font>

Korrekte CSV-Zeile:
"00:02:50,400","جوّ حاکمه","die Atmosphäre / Stimmung","فضای حاکم / جو","Die Charaktere sprechen über die Stimmung in der Vorstadt."

FORMATIERUNGS-REGELN:
- Gib AUSSCHLIESSLICH die rohen CSV-Daten aus. Kein Begrüßungstext, kein Markdown.
- Umschließe JEDES Feld zwingend mit doppelten Anführungszeichen ("...").
- Die erste Zeile muss exakt dieser Header sein:
"Zeitstempel","Farsi_Keyword","Deutsches_Wort","Erklärung auf Farsi","Erklärung im Kontext der Geschichte"

--- ZUSAMMENFASSUNG ---
{summary}

--- DEUTSCHE SRT ---
{de_srt}

--- PERSISCHE SRT ---
{fa_srt}
"""
        # HIER: Richtig eingerückt in den elif-Block!
        config = types.GenerateContentConfig(
            system_instruction=custom_system_instruction,
            temperature=0.3,
            response_schema=list[Vokabel], # Zwingt Gemini exakt in das Pydantic-Schema
            thinking_config=types.ThinkingConfig(thinking_budget=0)
        )

        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=prompt, # HIER FIX: 'prompt' statt 'prompt_contents'
            config=config
        )
        
        # Extrahierte Daten verarbeiten
        if response.parsed:
            vokabeln_raw = [v.model_dump() for v in response.parsed]
        else:
            vokabeln_raw = json.loads(response.text)
            
        if vokabeln_raw and csv_filepath:
            with open(csv_filepath, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.DictWriter(
                    f, 
                    fieldnames=["Zeitstempel", "Farsi_Keyword", "Deutsches_Wort", "Erklärung auf Farsi", "Erklärung im Kontext der Geschichte"],
                    quoting=csv.QUOTE_ALL
                )
                writer.writeheader()
                for v in vokabeln_raw:
                    writer.writerow({
                        "Zeitstempel": v["zeit"],
                        "Farsi_Keyword": v["keyword_farsi"],
                        "Deutsches_Wort": v["wort_deutsch"],
                        "Erklärung auf Farsi": v["erklaerung_farsi"],
                        "Erklärung im Kontext der Geschichte": v.get("erklaerung_kontext", "")
                    })
                    
    else:
        raise ValueError("Weder eine gültige CSV-Datei noch API-Zugangsdaten für die Neuerstellung gefunden.")

    if generate_csv_only and os.path.exists(csv_filepath):
        return None, csv_filepath

    # --- SICHERSTELLUNG: Falls csv_filepath dynamisch generiert wurde, setzen wir den Standard-Pfad ---
    if not csv_filepath:
        csv_filepath = farsi_srt_path.replace("_FA.srt", "_Vokabeln.csv")

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
    
    # Vor dem Einlesen der CSV einmal automatisch validieren, um sicherzustellen, dass alles passt  
    with open(csv_filepath, 'r', encoding='utf-8-sig') as f:
        csv_final_data = f.read()

    reader = csv.DictReader(StringIO(csv_final_data))
    for row in reader:
        vokabeln.append({
            'zeit': row['Zeitstempel'].strip(), 
            'keyword_farsi': row['Farsi_Keyword'].strip(),
            'wort_deutsch': row['Deutsches_Wort'].strip(),
            'erklaerung_farsi': row['Erklärung auf Farsi'].strip(),
            'erklaerung_kontext': row['Erklärung im Kontext der Geschichte'].strip()
        })

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
        if len(lines) < 3 or '-->' not in lines[1]:
            continue
            
        start_srt, end_srt = lines[1].split(' --> ')
        start_ass = srt_time_to_ass(start_srt.strip())
        end_ass = srt_time_to_ass(end_srt.strip())
        
        text_farsi = r'\N'.join(lines[2:])
        text_farsi = convert_html_to_ass(text_farsi)
        
        for vokabel in vokabeln:
            if vokabel['zeit'] in start_srt:
                open_tags = []
                close_tags = [] 
                
                if highlight_bold:
                    open_tags.append(r"\b1")
                    close_tags.append(r"\b0")
                if highlight_underline:
                    open_tags.append(r"\u1")
                    close_tags.append(r"\u0")
                if highlight_color:
                    open_tags.append(r"\c&HFFFF00&")
                    close_tags.append(r"\c")
                
                if open_tags:
                    tag_string = "".join(open_tags).replace('\\', '\\\\')
                    close_string = "".join(close_tags).replace('\\', '\\\\')
                    # DEIN FIX: Zwingt das Keyword durch \N auf eine eigene, isolierte Zeile
                    highlight_tag = rf"\\N{{{tag_string}}}\1{{{close_string}}}\\N"
                else:
                    highlight_tag = r"\1"
                    
                regex_pattern = vokabel['keyword_farsi'].replace(' ', r'(\s+|\\N)')
                text_farsi = re.sub(f"({regex_pattern})", highlight_tag, text_farsi)
                               
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
        # --- AUFRÄUMEN & RTL-GARANTIE ---
        # 1. Überschüssige Umbrüche (inklusive Leerzeichen dazwischen) zu einem zusammenfassen
        text_farsi = re.sub(r"(?:\s*\\N\s*)+", r"\\N", text_farsi)
        
        # 2. Entferne unnötige Umbrüche ganz am Anfang oder Ende des Satzes
        text_farsi = re.sub(r"^\\N|\\N$", "", text_farsi)
        
        # 3. Jede einzelne Zeile isoliert mit dem RTL-Steuerzeichen verpacken
        lines = text_farsi.split(r"\N")
        wrapped_lines = [f"\u202B{line.strip()}\u202C" for line in lines if line.strip()]
        text_farsi = r"\N".join(wrapped_lines)
        
        ass_events.append(f"Dialogue: 0,{start_ass},{end_ass},Standard,,0,0,0,,{text_farsi}")
    with open(ass_filepath, 'w', encoding='utf-8') as f:
        f.write(ass_header + '\n'.join(ass_events))
        
    return ass_filepath, csv_filepath