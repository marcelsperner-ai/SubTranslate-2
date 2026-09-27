import os
from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename
import pysrt
from dotenv import load_dotenv
from flask import render_template

from app.db import (
    create_translation, get_translation_by_id, update_translation, 
    get_db_logs, get_all_translations
)
from app.services.translation_service import start_translation_job

main_bp = Blueprint('main', __name__)
load_dotenv()

@main_bp.route('/api/projects', methods=['GET'])
def list_projects():
    """Gibt alle Projekte für die Archiv-Ansicht zurück."""
    return jsonify(get_all_translations())

@main_bp.route('/', methods=['GET'])
def index():
    """Lädt das Haupt-Frontend."""
    return render_template('index.html')

@main_bp.route('/api/upload', methods=['POST'])
def upload_file():
    """Nimmt eine SRT entgegen, speichert Einstellungen und legt ein Projekt an."""
    if 'file' not in request.files:
        return jsonify({"error": "Keine Datei hochgeladen"}), 400
        
    file = request.files['file']
    profile_key = request.form.get('profile_key', 'default')
    sync_offset = int(request.form.get('sync_offset', 0))
    episode_summary = request.form.get('episode_summary', '') # NEU aus dem FormData
    
    if file.filename == '':
        return jsonify({"error": "Dateiname leer"}), 400
        
    filename = secure_filename(file.filename)
    file_path = os.path.join(current_app.config['UPLOADS_DIR'], filename)
    file.save(file_path)
    
    try:
        subs = pysrt.open(file_path, encoding='utf-8')
    except UnicodeDecodeError:
        subs = pysrt.open(file_path, encoding='iso-8859-1')
        
    t_id = create_translation(filename, len(subs), sync_offset, profile_key)
    
    # NEU: Die Zusammenfassung sofort speichern
    save_project_settings(t_id, {'episode_summary': episode_summary})
    
    return jsonify({"message": "Projekt angelegt", "id": t_id}), 201

@main_bp.route('/api/start/<int:t_id>', methods=['POST'])
def start_job(t_id):
    """Startet den Hintergrund-Worker."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"error": "GEMINI_API_KEY fehlt in .env"}), 500
        
    success = start_translation_job(
        t_id, 
        api_key, 
        current_app.config['UPLOADS_DIR'], 
        current_app.config['OUTPUTS_DIR']
    )
    
    if success:
        return jsonify({"message": "Job gestartet"}), 200
    return jsonify({"error": "Job läuft bereits oder Status ungültig"}), 400

@main_bp.route('/api/pause/<int:t_id>', methods=['POST'])
def pause_job(t_id):
    """Setzt den Status auf pausiert und entzieht dem laufenden Worker das Token."""
    from app.db import pause_translation_job
    
    if pause_translation_job(t_id):
        return jsonify({"message": "Pause erfolgreich angefordert."}), 200
    return jsonify({"error": "Projekt konnte nicht pausiert werden (vielleicht nicht laufend)."}), 400

@main_bp.route('/api/status/<int:t_id>', methods=['GET'])
def get_status(t_id):
    """Gibt den aktuellen Fortschritt und die letzten Logs zurück (für Polling)."""
    t = get_translation_by_id(t_id)
    if not t:
        return jsonify({"error": "Projekt nicht gefunden"}), 404
        
    logs = get_db_logs(t_id, limit=15)
    return jsonify({
        "status": t['status'],
        "translated_lines": t['translated_lines'],
        "total_lines": t['total_lines'],
        "logs": logs
    })
from app.db import (
    create_translation, get_translation_by_id, update_translation, 
    get_db_logs, get_all_translations, save_project_settings, update_edtech_status
)
from app.services.edtech_service import validate_csv_timestamps, fix_csv_timestamps, gemini_followup_fix_mismatches, generate_learning_subtitles
from app.prompt_manager import load_prompts, get_edtech_instruction

@main_bp.route('/api/edtech/validate/<int:t_id>', methods=['GET'])
def validate_edtech(t_id):
    t = get_translation_by_id(t_id)
    if not t: 
        return jsonify({"error": "Projekt nicht gefunden"}), 404
    
    farsi_srt = os.path.join(current_app.config['OUTPUTS_DIR'], t['original_filename'].replace('.srt', '_FA.srt'))
    csv_file = os.path.join(current_app.config['OUTPUTS_DIR'], t['original_filename'].replace('.srt', '_Vokabeln.csv'))
    
    if not os.path.exists(farsi_srt):
        return jsonify({"error": "Farsi-SRT existiert noch nicht. Bitte zuerst übersetzen."}), 400
        
    if not os.path.exists(csv_file):
        return jsonify({"status": "no_csv_yet"})
        
    rows, ts_mismatches, kw_mismatches, fieldnames = validate_csv_timestamps(farsi_srt, csv_file)
    
    return jsonify({
        "status": "validated",
        "ts_mismatches": ts_mismatches,
        "kw_mismatches": kw_mismatches
    })

@main_bp.route('/api/edtech/fix/<int:t_id>', methods=['POST'])
def fix_edtech(t_id):
    try:
        t = get_translation_by_id(t_id)
        if not t: 
            return jsonify({"error": "Projekt nicht gefunden"}), 404
            
        farsi_srt = os.path.join(current_app.config['OUTPUTS_DIR'], t['original_filename'].replace('.srt', '_FA.srt'))
        csv_file = os.path.join(current_app.config['OUTPUTS_DIR'], t['original_filename'].replace('.srt', '_Vokabeln.csv'))
        
        if not os.path.exists(farsi_srt) or not os.path.exists(csv_file):
            return jsonify({"error": "Fehlende Dateien (SRT oder CSV) für die Reparatur."}), 400

        data = request.json or {}
        method = data.get('method')
        
        rows, ts_mismatches, kw_mismatches, fieldnames = validate_csv_timestamps(farsi_srt, csv_file)
        
        if method == 'python' and ts_mismatches:
            fix_csv_timestamps(csv_file, rows, fieldnames, ts_mismatches)
        elif method == 'gemini' and kw_mismatches:
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key: return jsonify({"error": "API Key fehlt"}), 500
            gemini_followup_fix_mismatches(api_key, farsi_srt, csv_file, kw_mismatches)
        elif method == 'ignore':
            pass
        else:
            return jsonify({"error": "Unbekannte Methode oder keine Fehler für diese Methode gefunden"}), 400
            
        return jsonify({"message": f"Reparatur mit '{method}' ausgeführt"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def str_to_bool(v):
    """Konvertiert Strings wie 'false' oder '0' sicher in Booleans."""
    if isinstance(v, bool): return v
    return str(v).lower() in ("yes", "true", "t", "1")

@main_bp.route('/api/edtech/generate/<int:t_id>', methods=['POST'])
def generate_edtech(t_id):
    try:
        t = get_translation_by_id(t_id)
        if not t: 
            return jsonify({"error": "Projekt nicht gefunden"}), 404
            
        data = request.json or {}
        
        # 1. Sicheres Parsing & Validierung VOR dem Speichern
        generate_csv_only = str_to_bool(data.get('generate_csv_only', False))
        try:
            infobox_duration = int(data.get('infobox_duration', t.get('infobox_duration', 7)))
            sync_offset_ms = int(data.get('ass_sync_offset', t.get('ass_sync_offset', 0)))
        except (TypeError, ValueError) as exc:
            return jsonify({"error": f"Ungültiger Zahlenwert übergeben: {exc}"}), 400
        hl_bold = str_to_bool(data.get('hl_bold', t.get('hl_bold', False)))
        hl_underline = str_to_bool(data.get('hl_underline', t.get('hl_underline', True)))
        hl_color = str_to_bool(data.get('hl_color', t.get('hl_color', False)))
        infobox_content = data.get('infobox_content', t.get('infobox_content', 'german_only'))
        episode_summary = data.get('episode_summary', t.get('episode_summary', ''))
        profile_key = data.get('profile_key', t.get('profile_key', 'default'))
        
        # 2. Sauberes Dictionary für die DB bauen und speichern
        merged_settings = {
            **t,
            'infobox_duration': infobox_duration,
            'ass_sync_offset': sync_offset_ms,
            'hl_bold': hl_bold,
            'hl_underline': hl_underline,
            'hl_color': hl_color,
            'infobox_content': infobox_content,
            'episode_summary': episode_summary,
            'profile_key': profile_key
        }
        save_project_settings(t_id, merged_settings)
        
        german_srt = os.path.join(current_app.config['UPLOADS_DIR'], t['original_filename'])
        farsi_srt = os.path.join(current_app.config['OUTPUTS_DIR'], t['original_filename'].replace('.srt', '_FA.srt'))
        ass_file = os.path.join(current_app.config['OUTPUTS_DIR'], t['original_filename'].replace('.srt', '_Interaktiv.ass'))
        
        prompts_data = load_prompts()
        custom_edtech = get_edtech_instruction(prompts_data, merged_settings.get('profile_key', 'default'))
        
        res_ass, res_csv = generate_learning_subtitles(
            farsi_srt_path=farsi_srt,
            ass_filepath=ass_file,
            german_srt_path=german_srt,
            summary=merged_settings.get('episode_summary', ''),
            api_key=os.getenv("GEMINI_API_KEY"),
            custom_system_instruction=custom_edtech,
            generate_csv_only=generate_csv_only,
            infobox_duration=infobox_duration,
            highlight_bold=hl_bold,
            highlight_underline=hl_underline,
            highlight_color=hl_color,
            infobox_content=merged_settings.get('infobox_content', 'german_only'),
            sync_offset_ms=sync_offset_ms
        )
        
        if generate_csv_only:
            if res_csv and os.path.exists(res_csv):
                return jsonify({"message": "CSV erfolgreich generiert"})
            return jsonify({"error": "CSV generiert, Datei aber auf dem Laufwerk nicht gefunden"}), 500
        else:
            if res_ass and os.path.exists(res_ass) and res_csv and os.path.exists(res_csv):
                update_edtech_status(t_id, 1)
                return jsonify({"message": "ASS und CSV erfolgreich generiert"})
            return jsonify({"error": "Generierung lief durch, aber Dateien fehlen auf dem Laufwerk"}), 500
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500