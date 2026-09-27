import streamlit as st
import sqlite3
import os
import time
import pysrt
import json
import re
import math
import smtplib
from email.message import EmailMessage
from datetime import datetime
from dotenv import load_dotenv
from google import genai
from google.genai import types
from prompt_manager import load_prompts, get_prompt_labels, get_system_instruction
from edtech import validate_csv_timestamps, fix_csv_timestamps, gemini_followup_fix_mismatches, generate_learning_subtitles
from prompt_manager import get_edtech_instruction

# --- 1. SETUP & API ---
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    st.error("🚨 Kein API Key gefunden! Bitte prüfe deine .env Datei.")
    st.stop()

client = genai.Client(api_key=api_key)

UPLOADS_DIR = "uploads"
OUTPUTS_DIR = "outputs"
DB_PATH = "translations.db"

os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(OUTPUTS_DIR, exist_ok=True)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS translations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_filename TEXT,
            status TEXT,
            total_lines INTEGER,
            translated_lines INTEGER,
            last_updated DATETIME,
            sync_offset INTEGER DEFAULT 0,
            edtech_done INTEGER DEFAULT 0,
            profile_key TEXT DEFAULT 'default'
        )
    ''')
    
    # Neue Spalten für Meta-Daten sicher hinzufügen, falls sie noch nicht existieren
    new_columns = {
        "batch_size": "INTEGER DEFAULT 40",
        "infobox_duration": "INTEGER DEFAULT 9",
        "ass_sync_offset": "INTEGER DEFAULT 0",
        "hl_bold": "INTEGER DEFAULT 0",
        "hl_underline": "INTEGER DEFAULT 1",
        "hl_color": "INTEGER DEFAULT 0",
        "infobox_content": "TEXT DEFAULT 'Nur deutsches Wort'",
        "episode_summary": "TEXT DEFAULT ''"
    }
    
    for col_name, col_type in new_columns.items():
        try:
            c.execute(f"ALTER TABLE translations ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError:
            pass # Spalte existiert bereits
            
    conn.commit()
    conn.close()

def save_project_settings(t_id, settings_dict):
    """Speichert alle Meta-Daten und Einstellungen für das aktuelle Projekt."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    query = '''
        UPDATE translations SET 
            batch_size = ?, infobox_duration = ?, ass_sync_offset = ?, 
            hl_bold = ?, hl_underline = ?, hl_color = ?, 
            infobox_content = ?, episode_summary = ?, sync_offset = ?, profile_key = ?
        WHERE id = ?
    '''
    c.execute(query, (
        settings_dict.get('batch_size', 40),
        settings_dict.get('infobox_duration', 9),
        settings_dict.get('ass_sync_offset', 0),
        1 if settings_dict.get('hl_bold') else 0,
        1 if settings_dict.get('hl_underline') else 0,
        1 if settings_dict.get('hl_color') else 0,
        settings_dict.get('infobox_content', 'Deutsches Wort + Farsi-Keyword'),
        settings_dict.get('episode_summary', ''),
        settings_dict.get('sync_offset', 0),
        settings_dict.get('profile_key', 'default'),
        t_id
    ))
    conn.commit()
    conn.close()

def update_edtech_status(t_id, status_val):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE translations SET edtech_done = ? WHERE id = ?", (status_val, t_id))
    conn.commit()
    conn.close()

# --- 2. DATENBANK HELPER ---
def get_all_translations():
    """Holt alle Übersetzungen für das Archiv, sortiert nach Aktualität."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM translations ORDER BY last_updated DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_latest_translation():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM translations ORDER BY last_updated DESC LIMIT 1")
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_translation_by_name(filename):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM translations WHERE original_filename = ?", (filename,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def create_translation(filename, total_lines, sync_offset, profile_key):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO translations (original_filename, status, total_lines, translated_lines, last_updated, sync_offset, profile_key)
        VALUES (?, 'pausiert', ?, 0, ?, ?, ?)
    ''', (filename, total_lines, datetime.now().isoformat(), sync_offset, profile_key))
    t_id = c.lastrowid
    conn.commit()
    conn.close()
    return t_id

def update_translation(t_id, translated_lines, status):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        UPDATE translations 
        SET translated_lines = ?, status = ?, last_updated = ? 
        WHERE id = ?
    ''', (translated_lines, status, datetime.now().isoformat(), t_id))
    conn.commit()
    conn.close()

def delete_translation(filename):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM translations WHERE original_filename = ?", (filename,))
    conn.commit()
    conn.close()
    if os.path.exists(os.path.join(UPLOADS_DIR, filename)):
        os.remove(os.path.join(UPLOADS_DIR, filename))
    out_name = filename.replace(".srt", "_FA.srt")
    if os.path.exists(os.path.join(OUTPUTS_DIR, out_name)):
        os.remove(os.path.join(OUTPUTS_DIR, out_name))

# --- E-MAIL HELPER (Multi-Anhang) ---
def send_email_with_attachments(receiver_email, subject, body, file_paths):
    sender_email = os.getenv("EMAIL_SENDER")
    sender_password = os.getenv("EMAIL_PASSWORD")
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", 465))

    if not sender_email or not sender_password:
        return False, "E-Mail-Zugangsdaten fehlen in der .env Datei."

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = sender_email
    msg['To'] = receiver_email
    msg.set_content(body)

    for file_path in file_paths:
        if file_path and os.path.exists(file_path):
            with open(file_path, 'rb') as f:
                file_data = f.read()
                file_name = os.path.basename(file_path)
            msg.add_attachment(file_data, maintype='text', subtype='plain', filename=file_name)

    try:
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
                server.login(sender_email, sender_password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(sender_email, sender_password)
                server.send_message(msg)
        return True, "Gesendet"
    except Exception as e:
        return False, str(e)

# --- 3. GEMINI API LOGIK MIT FARSI-CHECK ---
def translate_batch(text_batch, system_instruction, log_callback, max_retries=5):
    # Konfiguration mit Structured Outputs und ohne Thinking
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.3,
        response_schema=list[str],
        thinking_config=types.ThinkingConfig(thinking_budget=0)
    )
    contents = json.dumps(text_batch)
    
    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model="gemini-3.1-flash-lite", # 0.40$ pro 1 Mio. Output-Tokens
                contents=contents,
                config=config
            )
            
            # Bei Structured Outputs parst das Google SDK die Antwort oft direkt in `response.parsed`. 
            # Falls nicht, fallen wir sicherheitshalber auf den JSON-Text zurück.
            if response.parsed:
                translated_batch = response.parsed
            else:
                translated_batch = json.loads(response.text)
            
            if len(translated_batch) != len(text_batch):
                raise ValueError(f"Längen-Mismatch! Erwartet: {len(text_batch)}, Erhalten: {len(translated_batch)}")
            
            cleaned_batch = []
            
            for idx, (orig_text, trans_text) in enumerate(zip(text_batch, translated_batch)):
                # 1. Halluzinations-Check (wie bisher)
                if re.search(r'[a-zA-ZäöüÄÖÜß]', trans_text) and not re.search(r'[\u0600-\u06FF]', trans_text):
                    raise ValueError(f"Satz {idx+1} wurde nicht übersetzt (Halluzination): '{trans_text}'")
                
                # 2. DER AUTO-REPARATUR-FIX FÜR LITE-MODELLE
                # Wenn das Modell </font> und <font> zusammenklebt, brechen wir es wieder auf:
                trans_text = re.sub(r'</font>\s*<font', '</font>\n<font', trans_text)
                
                # 3. DER LINIEN-CHECK (Deine Idee in Perfektion)
                # Wir zählen die Zeilenumbrüche im deutschen Original und vergleichen sie mit dem Farsi-Text
                orig_lines = orig_text.count('\n')
                trans_lines = trans_text.count('\n')
                
                if orig_lines != trans_lines:
                    # Falls die Zeilenanzahl trotzdem nicht stimmt, protokollieren wir es als Warnung,
                    # lassen es aber durch, da es den Code nicht zum Absturz bringt (nur optisch unschön).
                    log_callback(f"ℹ️ Info: Zeilenanzahl bei Block {idx+1} weicht leicht ab. (Orig: {orig_lines+1}, Farsi: {trans_lines+1})")
                
                cleaned_batch.append(trans_text)
                
            return cleaned_batch
            
        except Exception as e:
            log_callback(f"⚠️ Warnung (Versuch {attempt}/{max_retries}): {str(e)}")
            if attempt < max_retries:
                log_callback("⏳ Warte 10 Sekunden vor Wiederholung des Batches...")
                time.sleep(10)
            else:
                log_callback("❌ Maximale Versuche erreicht. Breche Batch ab.")
                return None

def format_eta(seconds):
    if seconds < 60:
        return f"ca. {int(seconds)} Sekunden"
    else:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"ca. {mins} Min. {secs} Sek."

# --- 4. STREAMLIT UI ---
def main():
    st.set_page_config(page_title="SubTranslate AI", page_icon="🎬", layout="wide")
    init_db()
    
    if "active_translation" not in st.session_state:
        st.session_state.active_translation = get_latest_translation()
    if "is_running" not in st.session_state:
        st.session_state.is_running = False
    if "log_entries" not in st.session_state:
        st.session_state.log_entries = []
    if "batch_times" not in st.session_state:
        st.session_state.batch_times = []  # NEU

    def add_log(message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        st.session_state.log_entries.append(f"[{timestamp}] {message}")

    prompts_data = load_prompts()
    labels_to_ids = get_prompt_labels(prompts_data)

    # --- SEITENLEISTE ---
    with st.sidebar:
        t = st.session_state.get('active_translation')
        
        st.header("⚙️ Einstellungen")
        batch_size = st.slider("Batch-Größe (Sätze)", min_value=10, max_value=50, value=t.get('batch_size', 20) if t else 20, step=5)
        
        sync_offset = st.slider(
            "Synchronisation (Sync-Shift in ms)", 
            min_value=-3000, 
            max_value=3000, 
            value=t.get('sync_offset', 0) if t else 0, 
            step=50, 
            disabled=st.session_state.is_running,
            help="Verschiebt alle Zeitstempel."
        )
        st.divider()
        
        st.header("📂 Neues Projekt")
        
        # Den Index für das Dropdown-Menü anhand des gespeicherten Profils finden
        options_list = list(labels_to_ids.keys())
        default_index = 0
        if t and t.get('profile_key'):
            for i, (label, key) in enumerate(labels_to_ids.items()):
                if key == t['profile_key']:
                    default_index = i
                    break

        selected_label = st.selectbox("Serien-/Filmprofil:", options=options_list, index=default_index)
        selected_id = labels_to_ids[selected_label]
        active_prompt = get_system_instruction(prompts_data, selected_id)   
        with st.expander("Aktuellen System-Prompt anzeigen"):
            st.text(active_prompt)
        
        uploaded_file = st.file_uploader("Deutsche .srt Datei hochladen", type=["srt"])
        
        if uploaded_file is not None:
            existing_t = get_translation_by_name(uploaded_file.name)
            if existing_t:
                st.warning(f"Diese Übersetzung existiert bereits! ({existing_t['translated_lines']}/{existing_t['total_lines']} Zeilen)")
                colA, colB = st.columns(2)
                with colA:
                    if st.button("Fortsetzen", disabled=st.session_state.is_running):
                        st.session_state.active_translation = existing_t
                        st.session_state.is_running = False
                        st.session_state.log_entries = []
                        st.rerun()
                with colB:
                    if st.button("Überschreiben", disabled=st.session_state.is_running):
                        delete_translation(uploaded_file.name)
                        st.session_state.batch_times = []
                        st.session_state.log_entries = []
                        st.rerun()
            else:
                # --- NEU: SETUP-SCHRITT VOR DEM START ---
                st.markdown("---")
                st.subheader("📋 Episoden-Kontext")
                
                # Summaries YAML laden (falls vorhanden)
                sum_path = "summaries.yaml"
                summaries_data = {}
                if os.path.exists(sum_path):
                    import yaml
                    with open(sum_path, "r", encoding="utf-8") as sf:
                        summaries_data = yaml.safe_load(sf) or {}

                # Verfügbare Episoden für das aktuelle Profil holen
                profile_episodes = summaries_data.get(selected_id, {})
                ep_options = ["Benutzerdefiniert (Eingeben)"] + list(profile_episodes.keys())
                
                selected_ep_key = st.selectbox("Episode aus internem Speicher wählen:", options=ep_options)
                
                # Vorbelegung der Zusammenfassung basierend auf der Auswahl
                default_summary = ""
                if selected_ep_key != "Benutzerdefiniert (Eingeben)":
                    default_summary = profile_episodes.get(selected_ep_key, "")

                # Textarea, damit der Nutzer die Zusammenfassung sehen und anpassen kann
                final_summary_input = st.text_area("Zusammenfassung (vorab anpassbar):", value=default_summary, height=100)

                # Recovery Check / Wiederherstellung im Outputs-Ordner beibehalten
                out_name = uploaded_file.name.replace(".srt", "_FA.srt")
                out_path = os.path.join(OUTPUTS_DIR, out_name)
                
                if os.path.exists(out_path):
                    st.success("🔍 Vorhandene Übersetzung im 'outputs'-Ordner gefunden!")
                    if st.button("📂 Projekt aus Dateien wiederherstellen", type="primary"):
                        file_path = os.path.join(UPLOADS_DIR, uploaded_file.name)
                        with open(file_path, "wb") as f:
                            f.write(uploaded_file.getbuffer())
                            
                        try:
                            subs_in = pysrt.open(file_path, encoding='utf-8')
                        except UnicodeDecodeError:
                            subs_in = pysrt.open(file_path, encoding='iso-8859-1')
                            
                        t_id = create_translation(uploaded_file.name, len(subs_in), sync_offset, selected_id)
                        update_translation(t_id, len(subs_in), 'abgeschlossen')
                        
                        # Zusammenfassung direkt in DB speichern
                        save_project_settings(t_id, {'episode_summary': final_summary_input, 'profile_key': selected_id})
                        
                        st.session_state.active_translation = get_translation_by_name(uploaded_file.name)
                        st.toast("✅ Projekt erfolgreich wiederhergestellt!")
                        st.rerun()

                # Der verbindliche Start-Button, der erst NACH Prüfung der Zusammenfassung ausführt
                if st.button("Übersetzung starten", type="primary", disabled=st.session_state.is_running):
                    file_path = os.path.join(UPLOADS_DIR, uploaded_file.name)
                    with open(file_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    
                    try:
                        subs = pysrt.open(file_path, encoding='utf-8')
                    except UnicodeDecodeError:
                        subs = pysrt.open(file_path, encoding='iso-8859-1')
                        
                    # Projekt anlegen
                    t_id = create_translation(uploaded_file.name, len(subs), sync_offset, selected_id)
                    
                    # Direkt die mitgegebene Zusammenfassung abspeichern
                    save_project_settings(t_id, {
                        'episode_summary': final_summary_input,
                        'profile_key': selected_id,
                        'batch_size': batch_size,
                        'sync_offset': sync_offset
                    })
                    
                    st.session_state.active_translation = get_translation_by_name(uploaded_file.name)
                    st.session_state.is_running = True # Startet direkt im laufenden Modus
                    st.session_state.batch_times = []
                    st.session_state.log_entries = []
                    st.rerun()

        st.divider()
        
        # --- ARCHIV ---
        st.header("🗄️ Archiv")
        all_translations = get_all_translations()
        
        if not all_translations:
            st.info("Noch keine Projekte vorhanden.")
        else:
            for trans in all_translations:
                is_active = (st.session_state.active_translation and st.session_state.active_translation['id'] == trans['id'])
                status_emoji = "✅" if trans['status'] == 'abgeschlossen' else "⏸️" if trans['status'] == 'pausiert' else "▶️"
                
                # Sync-Offset Info
                offset_val = trans.get('sync_offset', 0)
                sync_text = f" | ⚡ {offset_val:+d} ms" if offset_val != 0 else " | ⚡ Kein Shift"
                
                # EdTech Status
                has_edtech = trans.get('edtech_done', 0) == 1
                edtech_badge = " | 🎓 Lernmaterial" if has_edtech else ""

                with st.container():
                    st.markdown(f"**{trans['original_filename']}**")
                    st.caption(f"{status_emoji} {trans['status'].capitalize()} ({trans['translated_lines']}/{trans['total_lines']} Zeilen){sync_text}{edtech_badge}")
                    
                    if is_active:
                        st.button("Aktuell geöffnet", key=f"active_{trans['id']}", disabled=True)
                    else:
                        if st.button("Projekt laden", key=f"load_{trans['id']}", disabled=st.session_state.is_running):
                            st.session_state.active_translation = trans
                            st.session_state.is_running = False
                            st.session_state.batch_times = []
                            st.session_state.log_entries = []
                            st.rerun()
                    st.divider()
                # EdTech Status auslesen
                has_edtech = trans.get('edtech_done', 0) == 1
                edtech_badge = " | 🎓 Lernmaterial vorhanden" if has_edtech else ""
                
                with st.container():
                    st.markdown(f"**{trans['original_filename']}**")
                    st.caption(f"{status_emoji} {trans['status'].capitalize()} ({trans['translated_lines']}/{trans['total_lines']} Zeilen){sync_text}{edtech_badge}")
    # --- HAUPTANSICHT ---
    if st.session_state.active_translation:
        t = st.session_state.active_translation
        st.title(f"🎬 Aktuelle Übersetzung: {t['original_filename']}")
        
        # NEU: Zweispaltiges Layout für Fortschritt und ETA
        col_prog, col_eta = st.columns([3, 1])
        progress = t['translated_lines'] / t['total_lines'] if t['total_lines'] > 0 else 0
        
        with col_prog:
            st.progress(progress)
            st.write(f"**Status:** {t['status']} | **Fortschritt:** {t['translated_lines']} von {t['total_lines']} Zeilen")
        # --- NEU: Unabhängige Zeitstempel-Korrektur (Non-KI) ---
        with st.expander("⚡ Erweiterte Synchronisation (Zeitstempel anpassen)"):
            st.write("Hier kannst du die Zeiten der aktuellen Datei verschieben, ohne den übersetzten Text zu verändern.")
            if st.button("Zeitstempel mit aktuellem Regler-Wert anpassen"):
                out_name = t['original_filename'].replace(".srt", "_FA.srt")
                out_path = os.path.join(OUTPUTS_DIR, out_name)
                
                if os.path.exists(out_path) and sync_offset != 0:
                    subs_reproc = pysrt.open(out_path, encoding='utf-8')
                    subs_reproc.shift(milliseconds=sync_offset)
                    subs_reproc.save(out_path, encoding='utf-8')
                    st.success(f"✅ Alle Zeitstempel der Datei wurden erfolgreich um {sync_offset} ms angepasst!")
                else:
                
                    st.warning("Entweder existiert die Zieldatei noch nicht oder der Regler steht auf 0 ms.")
        st.divider()
        with col_eta:
            if st.session_state.batch_times and st.session_state.is_running:
                avg_time = sum(st.session_state.batch_times) / len(st.session_state.batch_times)
                remaining_lines = t['total_lines'] - t['translated_lines']
                remaining_batches = math.ceil(remaining_lines / batch_size)
                st.info(f"⏳ **ETA:** {format_eta(avg_time * remaining_batches)}")
            elif st.session_state.is_running:
                st.info("⏳ **ETA:** Berechne...")    
        if t['translated_lines'] >= t['total_lines'] or t['status'] == 'abgeschlossen':
            st.success("🎉 Die Übersetzung ist vollständig abgeschlossen!")
            out_name = t['original_filename'].replace(".srt", "_FA.srt")
            out_path = os.path.join(OUTPUTS_DIR, out_name)
            
            if os.path.exists(out_path):
                # NEU: Button zum Anwenden des Sync-Shifts auf eine bestehende Datei
                if sync_offset != 0:
                    if st.button(f"⚡ Zeitstempel um {sync_offset} ms anpassen"):
                        subs_to_shift = pysrt.open(out_path, encoding='utf-8')
                        subs_to_shift.shift(milliseconds=sync_offset)
                        subs_to_shift.save(out_path, encoding='utf-8')
                        st.success(f"✅ Zeitstempel erfolgreich um {sync_offset} ms verschoben!")
                        st.rerun()
                with open(out_path, "rb") as f:
                    st.download_button("📥 Persische SRT herunterladen", f, file_name=out_name, mime="text/plain")
                # --- EDTECH / LERN-UNTERTITEL & VOKABELN ---
                st.divider()
                
                # PFADE DRINGEND VOR DER VERWENDUNG DEFINIEREN:
                ass_name = t['original_filename'].replace(".srt", "_Interaktiv.ass")
                ass_path = os.path.join(OUTPUTS_DIR, ass_name)
                
                csv_name = t['original_filename'].replace(".srt", "_Vokabeln.csv")
                csv_path = os.path.join(OUTPUTS_DIR, csv_name)
                
                # Erst jetzt kann files_exist fehlerfrei geprüft werden:
                files_exist = (t.get('edtech_done', 0) == 1) or (os.path.exists(ass_path) and os.path.exists(csv_path))
                
                with st.expander("🎓 EdTech: Interaktive Lern-Untertitel (.ass) & Vokabel-Einstellungen", expanded=files_exist):
                    st.write("Passe die Lern-Parameter an und generiere die .ass-Datei neu (auch aus vorhandenen CSV-Daten).")
                    
                    infobox_duration = st.slider("Infobox-Anzeigedauer (Sekunden)", min_value=3, max_value=15, value=t.get('infobox_duration', 7), step=1)
                    
                    st.write("**Hervorhebung der Keywords im Text (Mehrfachauswahl):**")
                    col_c1, col_c2, col_c3 = st.columns(3)
                    with col_c1:
                        hl_bold = st.checkbox("Fett (Bold)", value=bool(t.get('hl_bold', 0)), key=f"hl_b_{t['id']}")
                    with col_c2:
                        hl_underline = st.checkbox("Unterstrichen", value=bool(t.get('hl_underline', 1)), key=f"hl_u_{t['id']}")
                    with col_c3:
                        hl_color = st.checkbox("Farbig (Cyan)", value=bool(t.get('hl_color', 0)), key=f"hl_c_{t['id']}")
                    options_content = ["Nur deutsches Wort", "Deutsches Wort + Farsi-Keyword", "Deutsches Wort + Farsi-Erklärung"]
                    # HIER DEN STANDARDWERT ÄNDERN:
                    saved_content = t.get('infobox_content', 'Deutsches Wort + Farsi-Keyword')
                    # HIER DIE ZAHL ZU 1 ÄNDERN (Index 1 = Deutsches Wort + Farsi-Keyword)
                    idx_content = options_content.index(saved_content) if saved_content in options_content else 1 
                   
                    content_choice = st.selectbox(
                        "Inhalt der Infobox unter dem deutschen Wort:",
                        options=options_content,
                        index=idx_content,
                        key=f"content_{t['id']}"
                    )
                    content_map_real = {
                        "Nur deutsches Wort": "german_only",
                        "Deutsches Wort + Farsi-Keyword": "german_and_farsi_keyword",
                        "Deutsches Wort + Farsi-Erklärung": "german_and_farsi_explanation"
                    }
                    selected_content = content_map_real[content_choice]

                    ass_sync_offset = st.slider(
                        "ASS-Zeitversatz (ms)", 
                        min_value=-3000, 
                        max_value=3000, 
                        value=t.get('ass_sync_offset', 0), 
                        step=50,
                        help="Verschiebt die Infoboxen und Untertitel nachträglich in der ASS-Datei.",
                        key=f"sync_{t['id']}"
                    )

                    episode_summary = st.text_area("Kurze Zusammenfassung der Episode:", value=t.get('episode_summary', ''), height=80, key=f"sum_{t['id']}")
                    ass_name = t['original_filename'].replace(".srt", "_Interaktiv.ass")
                    ass_path = os.path.join(OUTPUTS_DIR, ass_name)
                    csv_name = t['original_filename'].replace(".srt", "_Vokabeln.csv")
                    csv_path = os.path.join(OUTPUTS_DIR, csv_name)

                    # --- IDEE 2: EDTECH PIPELINE (LIVE-LOGBUCH) ---
                    pipe_active = f"pipe_active_{t['id']}"
                    pipe_step = f"pipe_step_{t['id']}"

                    if pipe_active not in st.session_state:
                        st.session_state[pipe_active] = False
                    if pipe_step not in st.session_state:
                        st.session_state[pipe_step] = "idle"

                    # 1. Start-Button der Pipeline (JETZT IMMER SICHTBAR!)
                    button_label = "🔄 ASS mit neuen Einstellungen berechnen" if files_exist else "✨ Lernmaterial generieren (Pipeline starten)"
                    if st.button(button_label, key=f"start_pipe_{t['id']}", type="primary"):
                        st.session_state[pipe_active] = True
                        st.session_state[pipe_step] = "validate"
                        st.session_state[f"pipe_ignored_{t['id']}"] = False # Reset Ignore-Flag
                        st.rerun()

                    # 2. Die aktive Pipeline (aufklappbares Logbuch)
                    if st.session_state[pipe_active]:
                        status = st.status("🎓 EdTech Pipeline läuft...", expanded=True)
                        
                        with status:
                            # SCHRITT A: Validierung
                            if st.session_state[pipe_step] == "validate":
                                st.write("⏳ Lese Dateien und prüfe Zeitstempel...")
                                
                                if os.path.exists(csv_path):
                                    rows_data, ts_mismatches, kw_mismatches, fieldnames = validate_csv_timestamps(out_path, csv_path)
                                    
                                    if ts_mismatches or kw_mismatches:
                                        status.update(label="⚠️ Aktion erforderlich: Abweichungen gefunden", state="error")
                                        st.warning("Die automatische Analyse hat Asynchronitäten zwischen CSV und SRT festgestellt:")
                                        
                                        if ts_mismatches:
                                            with st.expander(f"🕒 {len(ts_mismatches)} abweichende Zeitstempel", expanded=True):
                                                for m in ts_mismatches:
                                                    st.markdown(f"- **{m['keyword']}**: CSV (`{m['csv_time']}`) ➔ SRT (`{m['srt_time']}`)")
                                        
                                        if kw_mismatches:
                                            with st.expander(f"❌ {len(kw_mismatches)} Farsi_Keywords nicht gefunden", expanded=True):
                                                for m in kw_mismatches:
                                                    st.markdown(f"- **{m['keyword']}** (CSV Zeit: `{m['csv_time']}`)")
                                                    
                                        st.markdown("### Wie möchtest du die Fehler beheben?")
                                        c1, c2, c3 = st.columns(3)
                                        
                                        with c1:
                                            if st.button("🤖 1. Gemini: Korrigieren", disabled=len(kw_mismatches)==0, use_container_width=True, key=f"btn_gem_{t['id']}"):
                                                with st.spinner("Gemini arbeitet..."):
                                                    gemini_followup_fix_mismatches(api_key, out_path, csv_path, kw_mismatches)
                                                    st.session_state[pipe_step] = "generate"
                                                    st.rerun() 
                                        with c2:
                                            if st.button("🛠️ 2. Python: Anpassen", disabled=len(ts_mismatches)==0, use_container_width=True, key=f"btn_py_{t['id']}"):
                                                with st.spinner("Zeitstempel werden synchronisiert..."):
                                                    fix_csv_timestamps(csv_path, rows_data, fieldnames, ts_mismatches)
                                                    st.session_state[pipe_step] = "generate"
                                                    st.rerun()
                                        with c3:
                                            if st.button("⏩ 3. Ignorieren", use_container_width=True, key=f"btn_ign_{t['id']}"):
                                                st.session_state[pipe_step] = "generate"
                                                st.session_state[f"pipe_ignored_{t['id']}"] = True # Setze Ignore-Flag
                                                st.rerun()
                                                
                                        st.stop() 
                                    else:
                                        st.write("✅ CSV ist synchron. Keine Abweichungen.")
                                        st.session_state[pipe_step] = "generate"
                                else:
                                    st.write("ℹ️ Keine CSV gefunden. Erstellung wird vorbereitet...")
                                    st.session_state[pipe_step] = "generate"

                            # SCHRITT B: Generierung der ASS-Datei
                            if st.session_state[pipe_step] == "generate":
                                st.write("⏳ Generiere interaktive Lern-Untertitel (.ass)...")
                                in_path = os.path.join(UPLOADS_DIR, t['original_filename'])
                                current_profile_key = t.get('profile_key', 'default')
                                custom_edtech_prompt = get_edtech_instruction(prompts_data, current_profile_key)

                                try:
                                    if os.path.exists(csv_path):
                                        res_ass, res_csv = generate_learning_subtitles(
                                            farsi_srt_path=out_path,
                                            ass_filepath=ass_path,
                                            csv_filepath=csv_path,
                                            infobox_duration=infobox_duration,
                                            highlight_bold=hl_bold,
                                            highlight_underline=hl_underline,
                                            highlight_color=hl_color,
                                            infobox_content=selected_content,
                                            sync_offset_ms=ass_sync_offset
                                        )
                                    else:
                                        if not episode_summary:
                                            status.update(label="❌ Fehler: Zusammenfassung fehlt", state="error")
                                            st.error("Bitte gib eine Zusammenfassung ein, da noch keine CSV existiert.")
                                            st.session_state[pipe_active] = False
                                            st.session_state[pipe_step] = "idle"
                                            st.stop()
                                            
                                        res_ass, res_csv = generate_learning_subtitles(
                                            farsi_srt_path=out_path,
                                            ass_filepath=ass_path,
                                            summary=episode_summary,
                                            api_key=api_key,
                                            german_srt_path=in_path,
                                            custom_system_instruction=custom_edtech_prompt,
                                            generate_csv_only=True,
                                            infobox_duration=infobox_duration,
                                            highlight_bold=hl_bold,
                                            highlight_underline=hl_underline,
                                            highlight_color=hl_color,
                                            infobox_content=selected_content,
                                            sync_offset_ms=ass_sync_offset
                                        )
                                        st.session_state[pipe_step] = "validate"
                                        st.rerun()
                                        
                                    update_edtech_status(t['id'], 1)
                                    st.session_state[pipe_step] = "complete"
                                    st.rerun()
                                    
                                except Exception as e:
                                    status.update(label="❌ Fehler bei der Generierung", state="error")
                                    st.error(f"Details: {e}")
                                    st.session_state[pipe_active] = False
                                    st.session_state[pipe_step] = "idle"
                                    st.stop()
                                    
                            # SCHRITT C: Abschluss & Erfolg (Logbuch bleibt offen)
                            if st.session_state[pipe_step] == "complete":
                                status.update(label="🎉 EdTech Pipeline erfolgreich abgeschlossen!", state="complete", expanded=True)
                                
                                # NEU: Ehrliches Feedback, falls ignoriert wurde
                                if st.session_state.get(f"pipe_ignored_{t['id']}", False):
                                    st.write("⚠️ CSV-Prüfung: Abweichungen wurden auf deinen Wunsch hin ignoriert.")
                                else:
                                    st.write("✅ CSV-Prüfung: Alle Zeitstempel sind synchron (oder wurden korrigiert).")
                                    
                                st.write("✅ Lernmaterialien: Interaktive ASS-Datei & Vokabel-CSV einsatzbereit.")
                                
                                # NEU: Klares visuelles Feedback
                                st.success("Die neue ASS-Datei wurde mit deinen aktuellen Einstellungen erzeugt und steht unten zum Download bereit!")
                                st.toast("🎉 ASS-Datei erfolgreich aktualisiert!", icon="✅")
                                
                                if st.button("Logbuch schließen", key=f"close_pipe_{t['id']}"):
                                    st.session_state[pipe_active] = False
                                    st.session_state[pipe_step] = "idle"
                                    st.rerun() 

                    # --- E-MAIL VERSAND BUTTON --- (Hier korrekte Einrückung: 20 Leerzeichen)
                    if files_exist:
                        receiver = os.getenv("EMAIL_RECEIVER")
                        if receiver:
                            if st.button("✉️ Aktualisierte Dateien per E-Mail versenden", key=f"send_email_{t['id']}"):
                                with st.spinner("Sende E-Mail..."):
                                    success, err = send_email_with_attachments(
                                        receiver,
                                        f"🎓 EdTech Lernmaterialien aktualisiert: {t['original_filename']}",
                                        "Hier sind deine frisch aktualisierten interaktiven Lern-Untertitel (.ass) und die Vokabel-CSV.",
                                        [ass_path, csv_path]
                                    )
                                    if success:
                                        st.toast("✉️ Erfolgreich per E-Mail versendet!", icon="✅")
                                    else:
                                        st.error(f"Fehler beim E-Mail-Versand: {err}")

                    # --- DOWNLOADS & VOLLSTÄNDIGE WINDOW-IN-WINDOW PREVIEW ---
                    if files_exist:
                        st.divider()
                        st.subheader("📥 Downloads & Vollständige Vorschau")
                        
                        col_d1, col_d2 = st.columns(2)
                        with col_d1:
                            if os.path.exists(ass_path):
                                with open(ass_path, "rb") as f:
                                    if st.download_button("📥 ASS herunterladen", f, file_name=ass_name, mime="text/plain", key=f"dl_ass_{t['id']}"):
                                        st.toast("📥 ASS-Untertitel heruntergeladen!", icon="✅")
                        with col_d2:
                            if os.path.exists(csv_path):
                                with open(csv_path, "rb") as f:
                                    if st.download_button("📥 Vokabel-CSV herunterladen", f, file_name=csv_name, mime="text/csv", key=f"dl_csv_{t['id']}"):
                                        st.toast("📥 Vokabel-CSV heruntergeladen!", icon="✅")
                                        
                        # Vollständige Fenster-in-Fenster Vorschau (mit automatischer Scrollbar)
                        with st.expander("👁️ Vollständige Dateivorschau anzeigen"):
                            prev_tab1, prev_tab2, prev_tab3 = st.tabs(["📄 Persische SRT", "🎓 Interaktive ASS", "📊 Vokabel-CSV"])
                            
                            with prev_tab1:
                                if os.path.exists(out_path):
                                    with open(out_path, "r", encoding="utf-8") as pf:
                                        st.code(pf.read(), language="text")
                                else:
                                    st.info("SRT noch nicht verfügbar.")
                                    
                            with prev_tab2:
                                if os.path.exists(ass_path):
                                    with open(ass_path, "r", encoding="utf-8") as pf:
                                        st.code(pf.read(), language="text")
                                else:
                                    st.info("ASS noch nicht generiert.")
                                    
                            with prev_tab3:
                                if os.path.exists(csv_path):
                                    with open(csv_path, "r", encoding="utf-8") as pf:
                                        st.code(pf.read(), language="csv")
                                else:
                                    st.info("CSV noch nicht generiert.")
            else:
                st.error("Zieldatei im Ordner 'outputs' nicht gefunden.")
        else:
            col1, col2, _ = st.columns([1, 1, 4])
            with col1:
                if not st.session_state.is_running:
                    if st.button("▶️ Fortsetzen", type="primary"):
                        st.session_state.is_running = True
                        update_translation(t['id'], t['translated_lines'], 'laufend')
                        add_log("▶️ Übersetzung gestartet / fortgesetzt.")
                        st.rerun()
            with col2:
                if st.session_state.is_running:
                    if st.button("⏸️ Pause", type="primary"):
                        st.session_state.is_running = False
                        update_translation(t['id'], t['translated_lines'], 'pausiert')
                        add_log("⏸️ Übersetzung pausiert.")
                        st.rerun()
                        
            st.divider()
            
            st.subheader("Live-Logbuch")
            log_container = st.empty()
            
            if st.session_state.log_entries:
                log_container.code("\n".join(st.session_state.log_entries[-15:]), language="markdown")
            
            if st.session_state.is_running:
                in_path = os.path.join(UPLOADS_DIR, t['original_filename'])
                out_name = t['original_filename'].replace(".srt", "_FA.srt")
                out_path = os.path.join(OUTPUTS_DIR, out_name)
                
                try:
                    subs_in = pysrt.open(in_path, encoding='utf-8')
                except UnicodeDecodeError:
                    subs_in = pysrt.open(in_path, encoding='iso-8859-1')
                
                if os.path.exists(out_path) and t['translated_lines'] > 0:
                    subs_work = pysrt.open(out_path, encoding='utf-8')
                else:
                    subs_work = subs_in
                
                start_index = t['translated_lines']
                
                # --- HIER NEU: EPISODEN-ZUSAMMENFASSUNG AN PROMPT ANHÄNGEN ---
                episode_summary = t.get('episode_summary', '').strip()
                if episode_summary:
                    final_system_prompt = f"{active_prompt}\n\nZUSAMMENFASSUNG DIESER EPISODE (Referenz: [Doppelhaushälfte (1x06) - Die Kamera](https://www.fernsehserien.de/doppelhaushaelfte/folgen/1x06-die-kamera-1531240)):\n{episode_summary}"
                else:
                    final_system_prompt = active_prompt
                # -------------------------------------------------------------
                
                for i in range(start_index, len(subs_work), batch_size):
                    if not st.session_state.is_running:
                        break
                        
                    batch_subs = subs_work[i:i + batch_size]
                    text_batch = [sub.text for sub in subs_in[i:i + batch_size]]
                    
                    add_log(f"➤ Sende Zeilen {i+1} bis {min(i+batch_size, len(subs_work))} an Gemini API...")
                    log_container.code("\n".join(st.session_state.log_entries[-15:]), language="markdown")
                    
                    # NEU: Zeitmessung starten
                    start_time = time.time()
                    
                    # HIER WICHTIG: Wir übergeben jetzt 'final_system_prompt' statt 'active_prompt'
                    translated_texts = translate_batch(text_batch, final_system_prompt, add_log)

                    # NEU: Zeitmessung stoppen & speichern (letzte 5 Werte behalten)
                    duration = time.time() - start_time
                    
                    if translated_texts:
                        st.session_state.batch_times.append(duration)
                        st.session_state.batch_times = st.session_state.batch_times[-5:]
                        
                        preview = translated_texts[0][:40].replace('\n', ' ') + "..."
                        add_log(f"✓ Output in {int(duration)} Sek. (Preview: '{preview}')")
                        for j, sub in enumerate(batch_subs):
                            sub.text = translated_texts[j]
                            
                        subs_work.save(out_path, encoding='utf-8')
                        new_translated_lines = i + len(batch_subs)
                        
                        update_translation(t['id'], new_translated_lines, 'laufend')
                        st.session_state.active_translation['translated_lines'] = new_translated_lines
                        
                        add_log("✓ Batch lokal gespeichert.")
                        log_container.code("\n".join(st.session_state.log_entries[-15:]), language="markdown")
                        
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        add_log("❌ Kritischer API-Fehler. Übersetzung wird pausiert.")
                        st.session_state.is_running = False
                        update_translation(t['id'], i, 'Fehler')
                        st.rerun()
                        break
                        
                if st.session_state.active_translation['translated_lines'] >= t['total_lines']:
                    st.session_state.is_running = False
                    
                    saved_offset = t.get('sync_offset', 0)
                    if saved_offset != 0:
                        subs_final = pysrt.open(out_path, encoding='utf-8')
                        subs_final.shift(milliseconds=saved_offset)
                        subs_final.save(out_path, encoding='utf-8')
                        add_log(f"⚡ Zeitstempel automatisch um {saved_offset} ms angepasst.")

                    add_log("🎉 Datei vollständig übersetzt!")
                    
                    # NEU: E-Mail mit der fertigen SRT-Datei im Anhang senden
                    receiver = os.getenv("EMAIL_RECEIVER")
                    if receiver:
                        add_log(f"✉️ Sende fertige Datei an {receiver}...")
                        success, error_msg = send_email_with_attachments(
                            receiver,
                            f"🎬 Übersetzung fertig: {t['original_filename']}",
                            "Deine Untertitel-Übersetzung ist abgeschlossen. Die fertige Datei findest du im Anhang.",
                            [out_path]
                        )
                        if success:
                            add_log("✉️ E-Mail erfolgreich gesendet!")
                        else:
                            add_log(f"⚠️ E-Mail-Fehler: {error_msg}")

                    update_translation(t['id'], t['total_lines'], 'abgeschlossen')
                    st.rerun()
        # --- AUTO-SAVE ALLER EINSTELLUNGEN ---
        # Speichert die aktuellen UI-Werte fließend in die Datenbank
        if t:
            current_settings = {
                'batch_size': batch_size,
                'sync_offset': sync_offset,
                'profile_key': selected_id,
                # EdTech-Werte nur speichern, wenn sie in diesem Rerun gerendert wurden (also die Variablen existieren)
                'infobox_duration': locals().get('infobox_duration', t.get('infobox_duration', 7)),
                'ass_sync_offset': locals().get('ass_sync_offset', t.get('ass_sync_offset', 0)),
                'hl_bold': locals().get('hl_bold', t.get('hl_bold', 0)),
                'hl_underline': locals().get('hl_underline', t.get('hl_underline', 1)),
                'hl_color': locals().get('hl_color', t.get('hl_color', 0)),
                'infobox_content': locals().get('content_choice', t.get('infobox_content', 'Deutsches Wort + Farsi-Keyword')),
                'episode_summary': locals().get('episode_summary', t.get('episode_summary', ''))
            }
            save_project_settings(t['id'], current_settings)
            
            # WICHTIG: Auch den Session-State aktualisieren, damit die UI beim nächsten Klick sofort die richtigen Werte hat
            for key, val in current_settings.items():
                st.session_state.active_translation[key] = val
    else:
        st.title("🎬 SubTranslate AI")
        st.info("Lade links eine Datei hoch oder wähle eine Übersetzung aus dem Archiv.")

if __name__ == "__main__":
    main()