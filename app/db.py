import sqlite3
import os
from datetime import datetime
import time

# Die Datenbank legen wir im Flask-typischen "instance"-Ordner ab
DB_PATH = "instance/translations.db"

def get_db_connection():
    """Erstellt eine Verbindung zur Datenbank und stellt sicher, dass der Ordner existiert."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
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
    
    # Neue Spalten für Meta-Daten (exakt wie im Original)
    new_columns = {
        "batch_size": "INTEGER DEFAULT 40",
        "infobox_duration": "INTEGER DEFAULT 9",
        "ass_sync_offset": "INTEGER DEFAULT 0",
        "hl_bold": "INTEGER DEFAULT 0",
        "hl_underline": "INTEGER DEFAULT 1",
        "hl_color": "INTEGER DEFAULT 0",
        "infobox_content": "TEXT DEFAULT 'Nur deutsches Wort'",
        "episode_summary": "TEXT DEFAULT ''",
        "custom_translation_prompt": "TEXT DEFAULT ''",
        "gemini_model": "TEXT DEFAULT 'gemini-3.1-flash-lite'",
        "translation_model": "TEXT DEFAULT 'gemini-3.1-flash-lite'",
        "edtech_model": "TEXT DEFAULT 'gemini-3.1-flash-lite'",
        "export_path": "TEXT DEFAULT ''",
        "archived": "INTEGER DEFAULT 0",
        "translation_started": "INTEGER DEFAULT 0",
        # --- NEU FÜR DEN HEARTBEAT & LEASE ---
        "heartbeat_at": "REAL DEFAULT 0",
        "worker_token": "TEXT DEFAULT NULL"
    }

    c.execute("PRAGMA table_info(translations)")
    existing_columns = {row[1] for row in c.fetchall()}
    
    for col_name, col_type in new_columns.items():
        try:
            c.execute(f"ALTER TABLE translations ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError:
            pass

    if "gemini_model" in existing_columns:
        if "translation_model" not in existing_columns:
            c.execute("UPDATE translations SET translation_model = gemini_model")
        if "edtech_model" not in existing_columns:
            c.execute("UPDATE translations SET edtech_model = gemini_model")
    if "translation_started" not in existing_columns:
        c.execute('''
            UPDATE translations SET translation_started = 1
            WHERE status != 'pausiert' OR translated_lines > 0 OR heartbeat_at > 0
        ''')
            
    # NEU FÜR FLASK: Eine separate Tabelle für das Live-Logbuch
    c.execute('''
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            translation_id INTEGER,
            timestamp TEXT,
            message TEXT
        )
    ''')
            
    conn.commit()
    conn.close()

def save_project_settings(t_id, settings_dict):
    conn = get_db_connection()
    c = conn.cursor()
    query = '''
        UPDATE translations SET 
            batch_size = ?, infobox_duration = ?, ass_sync_offset = ?, 
            hl_bold = ?, hl_underline = ?, hl_color = ?, 
            infobox_content = ?, episode_summary = ?, custom_translation_prompt = ?,
            sync_offset = ?, profile_key = ?, gemini_model = ?, translation_model = ?,
            edtech_model = ?, export_path = ?
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
        settings_dict.get('custom_translation_prompt', ''),
        settings_dict.get('sync_offset', 0),
        settings_dict.get('profile_key', 'default'),
        settings_dict.get('gemini_model') or settings_dict.get('translation_model', 'gemini-3.1-flash-lite'),
        settings_dict.get('translation_model') or settings_dict.get('gemini_model', 'gemini-3.1-flash-lite'),
        settings_dict.get('edtech_model') or settings_dict.get('gemini_model', 'gemini-3.1-flash-lite'),
        settings_dict.get('export_path', ''),
        t_id
    ))
    conn.commit()
    conn.close()

def update_translation_runtime_settings(t_id, batch_size, translation_model):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        UPDATE translations
        SET batch_size = ?, translation_model = ?, gemini_model = ?, last_updated = ?
        WHERE id = ?
    ''', (batch_size, translation_model, translation_model, datetime.now().isoformat(), t_id))
    success = c.rowcount > 0
    conn.commit()
    conn.close()
    return success

def acquire_translation_lock(t_id, worker_token):
    """Sichert den Job mit einem einzigartigen Token und setzt den initialen Heartbeat."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        UPDATE translations 
        SET status = 'laufend', last_updated = ?, heartbeat_at = ?, worker_token = ?, translation_started = 1
        WHERE id = ? AND status IN ('pausiert', 'Fehler')
    ''', (datetime.now().isoformat(), time.time(), worker_token, t_id))
    success = c.rowcount > 0
    conn.commit()
    conn.close()
    return success

def update_translation_progress(t_id, translated_lines, worker_token):
    """Aktualisiert Fortschritt NUR, wenn das Token noch übereinstimmt."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        UPDATE translations 
        SET translated_lines = ?, last_updated = ? 
        WHERE id = ? AND status = 'laufend' AND worker_token = ?
    ''', (translated_lines, datetime.now().isoformat(), t_id, worker_token))
    success = c.rowcount > 0
    conn.commit()
    conn.close()
    return success

def update_heartbeat(t_id, worker_token):
    """Erneuert den Heartbeat. Schlägt fehl, wenn der Job von einer Recovery übernommen wurde."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        UPDATE translations 
        SET heartbeat_at = ? 
        WHERE id = ? AND status = 'laufend' AND worker_token = ?
    ''', (time.time(), t_id, worker_token))
    success = c.rowcount > 0
    conn.commit()
    conn.close()
    return success

def set_translation_status(t_id, status, worker_token):
    """Sicheres Status-Update (z.B. Fehler oder Abschluss). Greift nur, wenn der Job noch 'laufend' ist."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        UPDATE translations 
        SET status = ?, last_updated = ? 
        WHERE id = ? AND worker_token = ? AND status = 'laufend'
    ''', (status, datetime.now().isoformat(), t_id, worker_token))
    success = c.rowcount > 0
    conn.commit()
    conn.close()
    return success

def pause_translation_job(t_id):
    """Setzt das Projekt auf Pause und entzieht SOFORT das Besitz-Token."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        UPDATE translations 
        SET status = 'pausiert', worker_token = NULL, last_updated = ? 
        WHERE id = ? AND status = 'laufend'
    ''', (datetime.now().isoformat(), t_id))
    success = c.rowcount > 0
    conn.commit()
    conn.close()
    return success

def update_edtech_status(t_id, status_val):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE translations SET edtech_done = ? WHERE id = ?", (status_val, t_id))
    conn.commit()
    conn.close()

def get_all_translations():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM translations ORDER BY last_updated DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def archive_translation(t_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE translations SET archived = 1, last_updated = ? WHERE id = ?", (datetime.now().isoformat(), t_id))
    success = c.rowcount > 0
    conn.commit()
    conn.close()
    return success

def unarchive_translation(t_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "UPDATE translations SET archived = 0, last_updated = ? WHERE id = ? AND archived = 1",
        (datetime.now().isoformat(), t_id)
    )
    success = c.rowcount > 0
    conn.commit()
    conn.close()
    return success

def update_translation_prompt(t_id, prompt):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE translations SET custom_translation_prompt = ?, last_updated = ? WHERE id = ?", (prompt, datetime.now().isoformat(), t_id))
    success = c.rowcount > 0
    conn.commit()
    conn.close()
    return success

def reset_translation_for_regeneration(t_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        UPDATE translations
        SET status = 'pausiert', translated_lines = 0, edtech_done = 0,
            worker_token = NULL, last_updated = ?
        WHERE id = ? AND status IN ('abgeschlossen', 'Fehler', 'pausiert')
    ''', (datetime.now().isoformat(), t_id))
    success = c.rowcount > 0
    conn.commit()
    conn.close()
    return success

def get_latest_translation():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM translations ORDER BY last_updated DESC LIMIT 1")
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_translation_by_name(filename):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM translations WHERE original_filename = ?", (filename,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_translation_by_id(t_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM translations WHERE id = ?", (t_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def create_translation(filename, total_lines, sync_offset, profile_key):
    conn = get_db_connection()
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
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        UPDATE translations 
        SET translated_lines = ?, status = ?, last_updated = ? 
        WHERE id = ?
    ''', (translated_lines, status, datetime.now().isoformat(), t_id))
    conn.commit()
    conn.close()

def delete_translation(filename):
    conn = get_db_connection()
    c = conn.cursor()
    # Log-Einträge gleich mit aufräumen
    c.execute("DELETE FROM logs WHERE translation_id IN (SELECT id FROM translations WHERE original_filename = ?)", (filename,))
    c.execute("DELETE FROM translations WHERE original_filename = ?", (filename,))
    conn.commit()
    conn.close()

# --- LOGGING HELPER FÜR DEN HINTERGRUND-WORKER ---
def add_db_log(t_id, message):
    conn = get_db_connection()
    c = conn.cursor()
    timestamp = datetime.now().strftime("%H:%M:%S")
    c.execute("INSERT INTO logs (translation_id, timestamp, message) VALUES (?, ?, ?)", (t_id, timestamp, message))
    conn.commit()
    conn.close()

def get_db_logs(t_id, limit=15):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT timestamp, message FROM logs WHERE translation_id = ? ORDER BY id DESC LIMIT ?", (t_id, limit))
    rows = c.fetchall()
    conn.close()
    # Damit die ältesten Logs oben stehen, drehen wir die Liste um
    return [f"[{row['timestamp']}] {row['message']}" for row in reversed(rows)]
