import os
import time
import pysrt
import difflib
import json
import re
import smtplib
import threading
import uuid
from email.message import EmailMessage
from datetime import datetime
from google import genai
from google.genai import types
from pydantic import BaseModel

from app.db import (
    get_translation_by_id, 
    update_translation, 
    add_db_log, 
    acquire_translation_lock, 
    update_translation_progress,
    update_heartbeat,
    set_translation_status,
    resolve_export_paths
)
from app.prompt_manager import load_prompts, get_system_instruction, append_episode_summary
from app.services.export_service import copy_file_to_export
from app.services.review_service import find_duplicate_suspects, restore_colors, review_path, save_review_items, add_review_items

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


class TranslatedCue(BaseModel):
    id: int
    source: str
    text: str


def _normalize_source(text):
    return " ".join(text.split())


def _source_matches(sent, echoed):
    sent, echoed = _normalize_source(sent), _normalize_source(echoed)
    return sent == echoed or difflib.SequenceMatcher(None, sent, echoed).ratio() >= 0.85


def _write_debug_record(debug_log_path, record):
    if not debug_log_path:
        return
    try:
        os.makedirs(os.path.dirname(debug_log_path), exist_ok=True)
        with open(debug_log_path, "a", encoding="utf-8") as debug_file:
            debug_file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as error:
        print(f"Debug-Log konnte nicht geschrieben werden: {error}", flush=True)


def _entry_field(entry, name):
    return entry.get(name) if isinstance(entry, dict) else getattr(entry, name, None)


def _split_entries(entries):
    ids, sources, texts = [], [], []
    for entry in entries:
        entry_id = _entry_field(entry, "id")
        source, text = _entry_field(entry, "source"), _entry_field(entry, "text")
        if not isinstance(entry_id, int) or not isinstance(source, str) or not isinstance(text, str):
            raise ValueError(f"Ungültiger Antworteintrag: {entry!r}")
        ids.append(entry_id)
        sources.append(source)
        texts.append(text)
    return ids, sources, texts


def translate_batch(client, text_batch, system_instruction, log_callback, model="gemini-3.1-flash-lite", max_retries=5, debug_log_path=None):
    batch_instruction = (
        f"{system_instruction.rstrip()}\n\n"
        f"Die Eingabe ist ein JSON-Array mit genau {len(text_batch)} Objekten der Form "
        '{"id": Nummer, "text": Untertitel}. Gib ein JSON-Array mit genau einem Objekt je Eingabeobjekt '
        'zurück: {"id": dieselbe Nummer, "source": der unveränderte Eingabetext dieser id, '
        '"text": Übersetzung genau dieses Eingabetextes}, in derselben Reihenfolge. '
        "Übersetze jeden Untertitel ausschließlich anhand seines eigenen Textes. Fasse niemals "
        "benachbarte Untertitel zusammen, überspringe keine und verschiebe keinen Inhalt in einen "
        "anderen Eintrag. Bewahre Zeilenumbrüche innerhalb eines Untertitels."
    )
    config = types.GenerateContentConfig(
        system_instruction=batch_instruction,
        temperature=0.3,
        response_schema=list[TranslatedCue],
        thinking_config=types.ThinkingConfig(thinking_budget=0)
    )
    expected_ids = list(range(1, len(text_batch) + 1))
    contents = json.dumps(
        [{"id": cue_id, "text": text} for cue_id, text in zip(expected_ids, text_batch)],
        ensure_ascii=False,
    )
    
    duplicate_retry_done = False
    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=config
            )

            raw_output = getattr(response, "text", None)
            parsed_output = response.parsed
            debug_output = raw_output
            output_label = "Rohantwort"
            if not debug_output and parsed_output is not None:
                debug_output = json.dumps(parsed_output, ensure_ascii=False)
                output_label = "geparste Antwort (response.text war leer)"
            print(
                f"\nGemini-{output_label} (Modell={model}, Versuch={attempt}, "
                f"Eingaben={len(text_batch)}):\n{debug_output or '<leer>'}\n",
                flush=True,
            )

            entries = parsed_output if parsed_output else json.loads(response.text)
            response_ids, response_sources, translated_batch = _split_entries(entries)
            source_mismatches = (
                [
                    cue_id for cue_id, sent, echoed in zip(expected_ids, text_batch, response_sources)
                    if not _source_matches(sent, echoed)
                ]
                if response_ids == expected_ids else []
            )
            _write_debug_record(debug_log_path, {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "model": model,
                "attempt": attempt,
                "request": json.loads(contents),
                "response": raw_output or debug_output,
                "ids_ok": response_ids == expected_ids,
                "source_mismatches": source_mismatches,
            })
            
            if response_ids != expected_ids or source_mismatches:
                candidates = getattr(response, "candidates", None) or []
                finish_reasons = [str(getattr(candidate, "finish_reason", None)) for candidate in candidates]
                usage = getattr(response, "usage_metadata", None)
                if not raw_output:
                    raw_output = json.dumps(translated_batch, ensure_ascii=False)
                diagnostic = (
                    f"Gemini-Antwortdiagnose: Modell={model}, Eingaben={len(text_batch)}, "
                    f"Ausgaben={len(translated_batch)}, IDs={response_ids}, Quelltext-Abweichungen={source_mismatches}, Finish-Reason={finish_reasons}, Nutzung={usage!r}"
                )
                log_callback(f"🔎 {diagnostic} (Rohantwort folgt im Flask-Terminal)")
                print(f"\n{diagnostic}\nRohantwort:\n{raw_output}\n", flush=True)
                if len(text_batch) > 1:
                    midpoint = len(text_batch) // 2
                    log_callback(
                        f"↪️ Batch mit {len(text_batch)} Einträgen wird wegen abweichender IDs oder Quelltexte "
                        f"in {midpoint} und {len(text_batch) - midpoint} Einträge geteilt."
                    )
                    first_half = translate_batch(
                        client, text_batch[:midpoint], system_instruction, log_callback,
                        model=model, max_retries=max_retries, debug_log_path=debug_log_path
                    )
                    if first_half is None:
                        return None
                    second_half = translate_batch(
                        client, text_batch[midpoint:], system_instruction, log_callback,
                        model=model, max_retries=max_retries, debug_log_path=debug_log_path
                    )
                    if second_half is None:
                        return None
                    return first_half + second_half
                raise ValueError(
                    f"Zuordnungs-Mismatch! Erwartete IDs: {expected_ids}, erhalten: {response_ids}, "
                    f"abweichende Quelltexte: {source_mismatches}"
                )
            
            cleaned_batch = []
            for idx, (orig_text, trans_text) in enumerate(zip(text_batch, translated_batch)):
                if re.search(r'[a-zA-ZäöüÄÖÜß]', trans_text) and not re.search(r'[\u0600-\u06FF]', trans_text):
                    raise ValueError(f"Satz {idx+1} wurde nicht übersetzt (Halluzination): '{trans_text}'")
                
                trans_text = re.sub(r'</font>\s*<font', '</font>\n<font', trans_text)
                
                trans_text, colors_fixed = restore_colors(orig_text, trans_text)
                if colors_fixed:
                    log_callback(f"🎨 Farben bei Block {idx+1} aus dem Original wiederhergestellt.")

                orig_lines = orig_text.count('\n')
                trans_lines = trans_text.count('\n')
                if orig_lines != trans_lines:
                    log_callback(f"ℹ️ Info: Zeilenanzahl bei Block {idx+1} weicht leicht ab.")
                
                cleaned_batch.append(trans_text)

            suspects = find_duplicate_suspects(text_batch, cleaned_batch)
            if suspects and not duplicate_retry_done and attempt < max_retries:
                duplicate_retry_done = True
                log_callback(
                    f"🔁 Verdacht auf doppelte Übersetzungen in {len(suspects)} Zeilenpaar(en); "
                    "Batch wird einmal neu angefordert."
                )
                continue
                
            return cleaned_batch
            
        except Exception as e:
            log_callback(f"⚠️ Warnung (Versuch {attempt}/{max_retries}): {str(e)}")
            if attempt < max_retries:
                log_callback("⏳ Warte 10 Sekunden vor Wiederholung des Batches...")
                time.sleep(10)
            else:
                log_callback("❌ Maximale Versuche erreicht. Breche Batch ab.")
                return None


def _translation_worker(t_id, api_key, uploads_dir, outputs_dir, worker_token, prompt_override=None):
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
        custom_prompt = prompt_override if prompt_override is not None else (t.get('custom_translation_prompt', '') or '')
        episode_summary = t.get('episode_summary', '').strip()
        gemini_model = t.get('translation_model') or t.get('gemini_model') or 'gemini-3.1-flash-lite'
        base_prompt = custom_prompt or get_system_instruction(prompts_data, t.get('profile_key', 'default'))
        final_system_prompt = append_episode_summary(base_prompt, episode_summary)

        client = genai.Client(api_key=api_key)
        batch_size = t.get('batch_size', 20)
        
        in_path = os.path.join(uploads_dir, t['original_filename'])
        out_name = t['original_filename'].replace(".srt", "_FA.srt")
        out_path = os.path.join(outputs_dir, out_name)
        
        # NEU: Einzigartige Temp-Datei für diesen spezifischen Worker-Run
        tmp_out_path = f"{out_path}.{worker_token}.tmp"
        debug_log_path = os.path.join(
            outputs_dir, "debug", out_name.replace("_FA.srt", "_gemini_raw.jsonl")
        )
        
        try:
            subs_in = pysrt.open(in_path, encoding='utf-8')
        except UnicodeDecodeError:
            subs_in = pysrt.open(in_path, encoding='iso-8859-1')
        
        if os.path.exists(out_path) and t['translated_lines'] > 0:
            subs_work = pysrt.open(out_path, encoding='utf-8')
        else:
            subs_work = subs_in
            
        start_index = t['translated_lines']
        review_file = review_path(outputs_dir, out_name)
        if start_index == 0:
            save_review_items(review_file, [])
        
        for i in range(start_index, len(subs_work), batch_size):
            # NEU: Checkt den Kill-Switch aus dem Heartbeat-Thread
            if lease_lost.is_set():
                log_cb("⏸️ Worker gestoppt: Heartbeat-Fehler oder Lease verloren.")
                break
                
            batch_subs = subs_work[i:i + batch_size]
            text_batch = [sub.text for sub in subs_in[i:i + batch_size]]
            log_cb(f"➤ Sende Zeilen {i+1} bis {min(i+batch_size, len(subs_work))} an API...")
            
            start_time = time.time()
            translated_texts = translate_batch(
                client, text_batch, final_system_prompt, log_cb, model=gemini_model,
                debug_log_path=debug_log_path
            )
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
                    
                suspects = find_duplicate_suspects(text_batch, translated_texts)
                if add_review_items(review_file, suspects, i):
                    log_cb(f"🧐 {len(suspects)} verdächtige Doppelung(en) zur Prüfung vorgemerkt.")

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
            subtitles_path, _ = resolve_export_paths(t.get('profile_key', 'default'), t.get('episode_key', ''))
            copy_file_to_export(out_path, subtitles_path, log_cb)

    except Exception as e:
        log_cb(f"❌ Systemfehler: {str(e)}")
        set_translation_status(t_id, 'Fehler', worker_token)
        
    finally:
        stop_heartbeat.set()
        # Falls der Worker abstürzt, die Temp-Datei sicherheitshalber aufräumen
        if 'tmp_out_path' in locals() and os.path.exists(tmp_out_path):
            os.remove(tmp_out_path)

def start_translation_job(t_id, api_key, uploads_dir, outputs_dir, prompt_override=None):
    worker_token = uuid.uuid4().hex 
    
    if not acquire_translation_lock(t_id, worker_token):
        return False 
        
    try:
        add_db_log(t_id, "▶️ Übersetzung gestartet (Lease erworben).")
        thread = threading.Thread(
            target=_translation_worker, 
            args=(t_id, api_key, uploads_dir, outputs_dir, worker_token, prompt_override),
            daemon=True
        )
        thread.start()
        return True
    except Exception as e:
        set_translation_status(t_id, 'Fehler', worker_token)
        add_db_log(t_id, f"❌ Fehler beim Starten des Hintergrund-Prozesses: {str(e)}")
        return False