import os
import time
import pysrt
import json
import re
import smtplib
import threading
import uuid
from email.message import EmailMessage
from datetime import datetime
from google import genai
from google.genai import types

from app.db import (
    get_translation_by_id, 
    update_translation, 
    add_db_log, 
    acquire_translation_lock, 
    update_translation_progress,
    update_heartbeat,
    set_translation_status
)
from app.prompt_manager import load_prompts, get_system_instruction

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


def translate_batch(client, text_batch, system_instruction, log_callback, max_retries=5):
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
                model="gemini-3.1-flash-lite", 
                contents=contents,
                config=config
            )
            
            if response.parsed:
                translated_batch = response.parsed
            else:
                translated_batch = json.loads(response.text)
            
            if len(translated_batch) != len(text_batch):
                raise ValueError(f"Längen-Mismatch! Erwartet: {len(text_batch)}, Erhalten: {len(translated_batch)}")
            
            cleaned_batch = []
            for idx, (orig_text, trans_text) in enumerate(zip(text_batch, translated_batch)):
                if re.search(r'[a-zA-ZäöüÄÖÜß]', trans_text) and not re.search(r'[\u0600-\u06FF]', trans_text):
                    raise ValueError(f"Satz {idx+1} wurde nicht übersetzt (Halluzination): '{trans_text}'")
                
                trans_text = re.sub(r'</font>\s*<font', '</font>\n<font', trans_text)
                
                orig_lines = orig_text.count('\n')
                trans_lines = trans_text.count('\n')
                if orig_lines != trans_lines:
                    log_callback(f"ℹ️ Info: Zeilenanzahl bei Block {idx+1} weicht leicht ab.")
                
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


def _translation_worker(t_id, api_key, uploads_dir, outputs_dir, worker_token):
    # --- HEARTBEAT THREAD ---
    stop_heartbeat = threading.Event()
    lease_lost = threading.Event()  # NEU: Kill-Switch für die Hauptschleife
    
    def heartbeat_loop():
        while not stop_heartbeat.is_set():
            try:
                if not update_heartbeat(t_id, worker_token):
                    lease_lost.set()
                    break
            except Exception as e:
                # Fängt SQLite-Fehler ab und signalisiert den Abbruch
                print(f"Heartbeat-Fehler bei Job {t_id}: {str(e)}")
                lease_lost.set()
                break
            stop_heartbeat.wait(30)

    hb_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    hb_thread.start()

    def log_cb(msg):
        add_db_log(t_id, msg)
        
    try:
        t = get_translation_by_id(t_id)
        if not t:
            return
            
        prompts_data = load_prompts()
        base_prompt = get_system_instruction(prompts_data, t.get('profile_key', 'default'))
        episode_summary = t.get('episode_summary', '').strip()
        final_system_prompt = f"{base_prompt}\n\nZUSAMMENFASSUNG DIESER EPISODE:\n{episode_summary}" if episode_summary else base_prompt

        client = genai.Client(api_key=api_key)
        batch_size = t.get('batch_size', 20)
        
        in_path = os.path.join(uploads_dir, t['original_filename'])
        out_name = t['original_filename'].replace(".srt", "_FA.srt")
        out_path = os.path.join(outputs_dir, out_name)
        
        # NEU: Einzigartige Temp-Datei für diesen spezifischen Worker-Run
        tmp_out_path = f"{out_path}.{worker_token}.tmp"
        
        try:
            subs_in = pysrt.open(in_path, encoding='utf-8')
        except UnicodeDecodeError:
            subs_in = pysrt.open(in_path, encoding='iso-8859-1')
        
        if os.path.exists(out_path) and t['translated_lines'] > 0:
            subs_work = pysrt.open(out_path, encoding='utf-8')
        else:
            subs_work = subs_in
            
        start_index = t['translated_lines']
        
        for i in range(start_index, len(subs_work), batch_size):
            # NEU: Checkt den Kill-Switch aus dem Heartbeat-Thread
            if lease_lost.is_set():
                log_cb("⏸️ Worker gestoppt: Heartbeat-Fehler oder Lease verloren.")
                break
                
            batch_subs = subs_work[i:i + batch_size]
            text_batch = [sub.text for sub in subs_in[i:i + batch_size]]
            log_cb(f"➤ Sende Zeilen {i+1} bis {min(i+batch_size, len(subs_work))} an API...")
            
            start_time = time.time()
            translated_texts = translate_batch(client, text_batch, final_system_prompt, log_cb)
            duration = time.time() - start_time
            
            if translated_texts:
                for j, sub in enumerate(batch_subs):
                    sub.text = translated_texts[j]
                    
                # 1. In TEMPORÄRE Datei speichern (keine Race Condition)
                subs_work.save(tmp_out_path, encoding='utf-8')
                new_translated_lines = i + len(batch_subs)
                
                # 2. Datenbank aktualisieren (Der ultimative Token-Check)
                if not update_translation_progress(t_id, new_translated_lines, worker_token):
                    log_cb("⚠️ DB-Update abgelehnt (Lease abgelaufen). Verwerfe Batch.")
                    if os.path.exists(tmp_out_path):
                        os.remove(tmp_out_path)
                    break
                    
                # 3. Wenn die DB ihr OK gibt: Temp-Datei zur echten Datei machen (Atomar)
                os.replace(tmp_out_path, out_path)
                    
                preview = translated_texts[0][:40].replace('\n', ' ') + "..."
                log_cb(f"✓ Output in {int(duration)} Sek. (Preview: '{preview}')")
            else:
                log_cb("❌ Kritischer API-Fehler.")
                set_translation_status(t_id, 'Fehler', worker_token)
                break
                
        final_t = get_translation_by_id(t_id)
        if final_t and final_t['status'] == 'laufend' and final_t['translated_lines'] >= final_t['total_lines'] and final_t['worker_token'] == worker_token:
            saved_offset = final_t.get('sync_offset', 0)
            if saved_offset != 0:
                subs_final = pysrt.open(out_path, encoding='utf-8')
                subs_final.shift(milliseconds=saved_offset)
                subs_final.save(out_path, encoding='utf-8')
                log_cb(f"⚡ Zeitstempel automatisch um {saved_offset} ms angepasst.")

            set_translation_status(t_id, 'abgeschlossen', worker_token)
            log_cb("🎉 Datei vollständig übersetzt!")
            
            receiver = os.getenv("EMAIL_RECEIVER")
            if receiver:
                log_cb(f"✉️ Sende fertige Datei an {receiver}...")
                success, error_msg = send_email_with_attachments(
                    receiver,
                    f"🎬 Übersetzung fertig: {final_t['original_filename']}",
                    "Deine Untertitel-Übersetzung ist abgeschlossen.",
                    [out_path]
                )
                if success:
                    log_cb("✉️ E-Mail erfolgreich gesendet!")
                else:
                    log_cb(f"⚠️ E-Mail-Fehler: {error_msg}")

    except Exception as e:
        log_cb(f"❌ Systemfehler: {str(e)}")
        set_translation_status(t_id, 'Fehler', worker_token)
        
    finally:
        stop_heartbeat.set()
        # Falls der Worker abstürzt, die Temp-Datei sicherheitshalber aufräumen
        if 'tmp_out_path' in locals() and os.path.exists(tmp_out_path):
            os.remove(tmp_out_path)

def start_translation_job(t_id, api_key, uploads_dir, outputs_dir):
    worker_token = uuid.uuid4().hex 
    
    if not acquire_translation_lock(t_id, worker_token):
        return False 
        
    try:
        add_db_log(t_id, "▶️ Übersetzung gestartet (Lease erworben).")
        thread = threading.Thread(
            target=_translation_worker, 
            args=(t_id, api_key, uploads_dir, outputs_dir, worker_token),
            daemon=True
        )
        thread.start()
        return True
    except Exception as e:
        set_translation_status(t_id, 'Fehler', worker_token)
        add_db_log(t_id, f"❌ Fehler beim Starten des Hintergrund-Prozesses: {str(e)}")
        return False