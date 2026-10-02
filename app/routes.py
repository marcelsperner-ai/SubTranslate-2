import csv
import os
from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename
import pysrt
from dotenv import load_dotenv
from flask import render_template
from flask import send_file
from app.prompt_manager import load_prompts, get_edtech_instruction, get_system_instruction, append_episode_summary
import yaml
from app.db import (
    create_translation, get_translation_by_id, update_translation, 
    get_db_logs, get_all_translations, archive_translation, unarchive_translation,
    reset_translation_for_regeneration, update_translation_runtime_settings,
    get_default_settings, save_default_settings,
    get_export_locations, save_export_location, resolve_export_paths,
    update_project_name, save_project_settings
)
from app.services.translation_service import start_translation_job
from app.services.export_service import copy_file_to_export
from app.services.subtitle_conversion_service import convert_ttml_to_srt

main_bp = Blueprint('main', __name__)
load_dotenv()
GEMINI_MODEL_IDS = {
    'gemini-3.1-flash-lite',
    'gemini-3-flash',
    'gemini-3.8-flash',
    'gemini-3.7-flash',
    'gemini-3.6-flash',
    'gemini-3.5-flash',
    'gemini-3.5-flash-lite',
    'gemini-3.1-pro-preview',
}

def suggested_project_name(profile_key, episode_key='', original_filename='', prompt_profiles=None):
    if profile_key == 'default':
        return os.path.splitext(original_filename)[0] or 'Projekt'
    try:
        profiles = prompt_profiles if prompt_profiles is not None else load_prompts()
        profile = profiles.get(profile_key, {})
    except (OSError, yaml.YAMLError):
        profile = {}
    series_name = (profile.get('label') or profile.get('name') or profile_key).split(' (', 1)[0].strip()
    episode_name = episode_key.replace('x', '.') if episode_key and episode_key != '__custom__' else ''
    return f"{series_name} {episode_name}".strip()

def add_project_display_names(project, prompt_profiles=None):
    suggested_name = suggested_project_name(
        project.get('profile_key', 'default'),
        project.get('episode_key', ''),
        project.get('original_filename', ''),
        prompt_profiles
    )
    project['suggested_project_name'] = suggested_name
    project['project_name'] = project.get('project_name') or suggested_name
    return project

@main_bp.route('/api/projects', methods=['GET'])
def list_projects():
    """Liefert aktive und archivierte Projekte samt Dateistatus für die UI."""
    outputs_dir = current_app.config['OUTPUTS_DIR']
    projects = get_all_translations()
    try:
        prompt_profiles = load_prompts()
    except (OSError, yaml.YAMLError):
        prompt_profiles = {}
    for project in projects:
        add_project_display_names(project, prompt_profiles)
        base_name = project['original_filename'].replace('.srt', '')
        project['available_downloads'] = {
            'srt': os.path.exists(os.path.join(outputs_dir, f'{base_name}_FA.srt')),
            'ass': bool(project.get('edtech_done')) and os.path.exists(os.path.join(outputs_dir, f'{base_name}_Interaktiv.ass')),
            'csv': os.path.exists(os.path.join(outputs_dir, f'{base_name}_Vokabeln.csv')),
        }
    return jsonify(projects)

@main_bp.route('/api/archive/<int:t_id>', methods=['POST'])
def archive_project(t_id):
    project = get_translation_by_id(t_id)
    if not project:
        return jsonify({"error": "Projekt nicht gefunden"}), 404
    base_name = project['original_filename'].replace('.srt', '')
    outputs_dir = current_app.config['OUTPUTS_DIR']
    has_srt = os.path.exists(os.path.join(outputs_dir, f'{base_name}_FA.srt'))
    has_ass = bool(project.get('edtech_done')) and os.path.exists(os.path.join(outputs_dir, f'{base_name}_Interaktiv.ass'))
    if project.get('status') != 'abgeschlossen' or not has_srt or not has_ass:
        return jsonify({"error": "Archivieren ist erst möglich, wenn SRT und ASS vollständig erstellt wurden."}), 409
    if archive_translation(t_id):
        return jsonify({"message": "Projekt archiviert"})
    return jsonify({"error": "Projekt nicht gefunden"}), 404

@main_bp.route('/api/unarchive/<int:t_id>', methods=['POST'])
def unarchive_project(t_id):
    project = get_translation_by_id(t_id)
    if not project:
        return jsonify({"error": "Projekt nicht gefunden"}), 404
    if not project.get('archived'):
        return jsonify({"message": "Projekt ist bereits aktiv"})
    if unarchive_translation(t_id):
        return jsonify({"message": "Projekt wiederhergestellt"})
    return jsonify({"error": "Projekt konnte nicht wiederhergestellt werden"}), 409

@main_bp.route('/', methods=['GET'])
def index():
    """Lädt das Haupt-Frontend."""
    return render_template('index.html')

@main_bp.route('/lernkarten/<int:t_id>', methods=['GET'])
def flashcards_page(t_id):
    """Lädt die eigenständige Lernkarten-Seite (öffnet sich im neuen Tab)."""
    t = get_translation_by_id(t_id)
    if not t:
        return render_template('flashcards.html', t_id=t_id, project_name='', project_missing=True), 404
    add_project_display_names(t)
    return render_template('flashcards.html', t_id=t_id, project_name=t['project_name'], project_missing=False)

@main_bp.route('/api/settings/defaults', methods=['GET'])
def get_app_default_settings():
    """Liefert die globalen Default-Einstellungen für neue Projekte."""
    return jsonify(get_default_settings())

@main_bp.route('/api/settings/defaults', methods=['POST'])
def update_app_default_settings():
    """Speichert die globalen Default-Einstellungen; wirkt sich nur auf neue Projekte aus."""
    data = request.get_json(silent=True) or {}
    srt = data.get('srt', {})
    edtech = data.get('edtech', {})

    try:
        batch_size = int(srt.get('batch_size', 40))
        sync_offset = int(srt.get('sync_offset', 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Ungültige Batch-Größe oder ungültiger Sync-Offset."}), 400
    if not 1 <= batch_size <= 500:
        return jsonify({"error": "Die Batch-Größe muss zwischen 1 und 500 liegen."}), 400
    translation_model = srt.get('translation_model', 'gemini-3.1-flash-lite')
    if translation_model not in GEMINI_MODEL_IDS:
        return jsonify({"error": "Ungültige Gemini-Modellauswahl für das SRT-Modul."}), 400

    try:
        infobox_duration = int(edtech.get('infobox_duration', 9))
        ass_sync_offset = int(edtech.get('ass_sync_offset', 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Ungültige Infobox-Dauer oder ungültiger ASS-Sync-Offset."}), 400
    edtech_model = edtech.get('edtech_model', 'gemini-3.1-flash-lite')
    if edtech_model not in GEMINI_MODEL_IDS:
        return jsonify({"error": "Ungültige Gemini-Modellauswahl für das EdTech-Modul."}), 400
    infobox_content = edtech.get('infobox_content', 'german_only')

    save_default_settings('srt', {
        'batch_size': batch_size,
        'translation_model': translation_model,
        'sync_offset': sync_offset,
    })
    save_default_settings('edtech', {
        'infobox_duration': infobox_duration,
        'ass_sync_offset': ass_sync_offset,
        'infobox_content': infobox_content,
        'hl_bold': bool(edtech.get('hl_bold')),
        'hl_underline': bool(edtech.get('hl_underline')),
        'hl_color': bool(edtech.get('hl_color')),
        'edtech_model': edtech_model,
    })
    return jsonify(get_default_settings())

def build_export_path_payload():
    """Baut die nach Serie/Staffel gruppierte Antwortstruktur für die Export-Pfad-Settings."""
    grouped = {}
    for row in get_export_locations():
        entry = grouped.setdefault(row['profile_key'], {})
        entry[row['season'] or 'default'] = {
            'subtitles_path': row['subtitles_path'] or '',
            'vocab_path': row['vocab_path'] or '',
        }
    return grouped

@main_bp.route('/api/settings/export-paths', methods=['GET'])
def get_export_path_settings():
    """Liefert alle konfigurierten Export-Zielordner, gruppiert nach Serie."""
    return jsonify(build_export_path_payload())

@main_bp.route('/api/settings/export-paths', methods=['POST'])
def update_export_path_settings():
    """Speichert Export-Zielordner für eine Serie (season='') und/oder einzelne Staffeln."""
    data = request.get_json(silent=True) or {}
    profile_key = (data.get('profile_key') or '').strip()
    if not profile_key:
        return jsonify({"error": "Serie fehlt."}), 400
    entries = data.get('entries', [])
    for entry in entries:
        season = (entry.get('season') or '').strip()
        subtitles_path = (entry.get('subtitles_path') or '').strip()
        vocab_path = (entry.get('vocab_path') or '').strip()
        save_export_location(profile_key, season, subtitles_path, vocab_path)
    return jsonify(build_export_path_payload())

def get_episode_summary(profile_key, episode_key):
    base_dir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    summaries_path = os.path.join(base_dir, 'summaries.yaml')
    if not episode_key or not os.path.exists(summaries_path):
        return ""

    try:
        with open(summaries_path, 'r', encoding='utf-8') as summaries_file:
            summaries_data = yaml.safe_load(summaries_file) or {}
        return summaries_data.get(profile_key, {}).get(episode_key, "")
    except Exception as e:
        print(f"Fehler beim Lesen der summaries.yaml: {e}")
        return ""

def build_prompt_payload(profile_key, episode_summary, custom_translation_prompt=''):
    prompts_data = load_prompts()
    base_prompt = get_system_instruction(prompts_data, profile_key)
    trans_prompt = append_episode_summary(custom_translation_prompt or base_prompt, episode_summary)
    edtech_prompt = append_episode_summary(
        get_edtech_instruction(prompts_data, profile_key), episode_summary
    )
    return {
        "translation_prompt": trans_prompt,
        "edtech_prompt": edtech_prompt
    }

@main_bp.route('/api/upload', methods=['POST'])
def upload_file():
    """Nimmt SRT oder TTML entgegen und legt ein SRT-basiertes Projekt an."""
    if 'file' not in request.files:
        return jsonify({"error": "Keine Datei hochgeladen"}), 400
        
    file = request.files['file']
    profile_key = request.form.get('profile_key', 'default')
    episode_key = request.form.get('episode', '')
    custom_translation_prompt = request.form.get('custom_translation_prompt', '')
    episode_summary_override = request.form.get('episode_summary_override', '')
    defaults = get_default_settings()
    srt_defaults = defaults['srt']
    edtech_defaults = defaults['edtech']
    sync_offset = int(request.form.get('sync_offset', srt_defaults['sync_offset']))
    batch_size = int(request.form.get('batch_size', srt_defaults['batch_size']))
    translation_model = request.form.get('translation_model', request.form.get('gemini_model', srt_defaults['translation_model']))
    edtech_model = request.form.get('edtech_model', edtech_defaults['edtech_model'])
    if translation_model not in GEMINI_MODEL_IDS or edtech_model not in GEMINI_MODEL_IDS:
        return jsonify({"error": "Ungültige Gemini-Modellauswahl."}), 400
    
    if file.filename == '':
        return jsonify({"error": "Dateiname leer"}), 400

    real_summary = (
        episode_summary_override.strip()
        if episode_key == '__custom__'
        else get_episode_summary(profile_key, episode_key)
    )
        
    filename = secure_filename(file.filename)
    if not filename:
        return jsonify({"error": "Ungueltiger Dateiname."}), 400

    extension = os.path.splitext(filename)[1].lower()
    if extension not in {'.srt', '.xml', '.ttml'}:
        return jsonify({"error": "Unterstuetzte Formate: SRT, XML/TTML."}), 400

    source_content = file.read()
    if not source_content:
        return jsonify({"error": "Die Datei ist leer."}), 400

    stem = os.path.splitext(filename)[0]
    content_prefix = source_content.lstrip(b'\xef\xbb\xbf \t\r\n')
    is_ttml = extension in {'.xml', '.ttml'} or content_prefix.startswith((b'<?xml', b'<tt'))
    if is_ttml:
        try:
            srt_content = convert_ttml_to_srt(source_content)
        except ValueError as error:
            return jsonify({"error": str(error)}), 400
        project_filename = f'{stem}.srt'
    else:
        try:
            srt_content = source_content.decode('utf-8-sig')
        except UnicodeDecodeError:
            srt_content = source_content.decode('iso-8859-1')
        project_filename = f'{stem}.srt'

    source_filename = filename
    if is_ttml and source_filename.casefold() == project_filename.casefold():
        source_filename = f'{stem}.source.xml'

    try:
        subs = pysrt.from_string(srt_content)
    except Exception as error:
        return jsonify({"error": f"SRT konnte nicht gelesen werden: {error}"}), 400
    if not subs:
        return jsonify({"error": "Die Datei enthaelt keine Untertitel-Cues."}), 400

    uploads_dir = current_app.config['UPLOADS_DIR']
    source_path = os.path.join(uploads_dir, source_filename)
    project_path = os.path.join(uploads_dir, project_filename)
    with open(source_path, 'wb') as source_file:
        source_file.write(source_content)
    if project_path != source_path:
        with open(project_path, 'w', encoding='utf-8', newline='') as project_file:
            project_file.write(srt_content)
        
    project_name = suggested_project_name(profile_key, episode_key, project_filename)
    t_id = create_translation(project_filename, len(subs), sync_offset, profile_key, episode_key, project_name)
    
    # Zusammenfassung und Upload-Einstellungen gemeinsam speichern.
    save_project_settings(t_id, {
        'batch_size': batch_size,
        'custom_translation_prompt': custom_translation_prompt,
        'episode_summary': real_summary,
        'profile_key': profile_key,
        'sync_offset': sync_offset,
        'gemini_model': translation_model,
        'translation_model': translation_model,
        'edtech_model': edtech_model,
        'export_path': request.form.get('export_path', ''),
        'infobox_duration': edtech_defaults['infobox_duration'],
        'ass_sync_offset': edtech_defaults['ass_sync_offset'],
        'infobox_content': edtech_defaults['infobox_content'],
        'hl_bold': edtech_defaults['hl_bold'],
        'hl_underline': edtech_defaults['hl_underline'],
        'hl_color': edtech_defaults['hl_color'],
    })
    
    return jsonify({
        "message": "Projekt angelegt",
        "id": t_id,
        "original_filename": project_filename,
        "source_filename": source_filename,
        "source_format": 'ttml' if is_ttml else 'srt',
    }), 201

@main_bp.route('/api/project/<int:t_id>/name', methods=['PUT'])
def rename_project(t_id):
    project = get_translation_by_id(t_id)
    if not project:
        return jsonify({"error": "Projekt nicht gefunden"}), 404
    data = request.get_json(silent=True) or {}
    project_name = data.get('project_name')
    if not isinstance(project_name, str):
        return jsonify({"error": "Projektname muss Text sein."}), 400
    project_name = project_name.strip()
    if not project_name or len(project_name) > 120:
        return jsonify({"error": "Der Projektname muss zwischen 1 und 120 Zeichen lang sein."}), 400
    if not update_project_name(t_id, project_name):
        return jsonify({"error": "Projektname konnte nicht gespeichert werden."}), 500
    return jsonify({"project_name": project_name})

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

@main_bp.route('/api/project/<int:t_id>/translation-settings', methods=['POST'])
def update_translation_settings(t_id):
    t = get_translation_by_id(t_id)
    if not t:
        return jsonify({"error": "Projekt nicht gefunden"}), 404
    data = request.get_json(silent=True) or {}
    try:
        batch_size = int(data.get('batch_size', t.get('batch_size', 40)))
    except (TypeError, ValueError):
        return jsonify({"error": "Ungültige Batch-Größe."}), 400
    translation_model = data.get('translation_model', t.get('translation_model') or t.get('gemini_model'))
    if not 1 <= batch_size <= 500:
        return jsonify({"error": "Die Batch-Größe muss zwischen 1 und 500 liegen."}), 400
    if translation_model not in GEMINI_MODEL_IDS:
        return jsonify({"error": "Ungültige Gemini-Modellauswahl."}), 400
    if not update_translation_runtime_settings(t_id, batch_size, translation_model):
        return jsonify({"error": "Projekt-Einstellungen konnten nicht gespeichert werden."}), 500
    return jsonify({
        "message": "Gespeichert; gilt beim nächsten Start oder Fortsetzen.",
        "applies_on_next_start": True,
        "translation_started": bool(t.get('translation_started')),
    })

@main_bp.route('/api/pause/<int:t_id>', methods=['POST'])
def pause_job(t_id):
    """Setzt den Status auf pausiert und entzieht dem laufenden Worker das Token."""
    from app.db import pause_translation_job
    
    if pause_translation_job(t_id):
        return jsonify({"message": "Pause erfolgreich angefordert."}), 200
    return jsonify({"error": "Projekt konnte nicht pausiert werden (vielleicht nicht laufend)."}), 400

@main_bp.route('/api/regenerate/<int:t_id>', methods=['POST'])
def regenerate_translation(t_id):
    """Startet eine SRT-Neugenerierung mit einem nur für diesen Lauf geltenden Prompt."""
    t = get_translation_by_id(t_id)
    data = request.get_json(silent=True) or {}
    prompt = data.get('translation_prompt', '').strip()
    if not t:
        return jsonify({"error": "Projekt nicht gefunden"}), 404
    if not prompt:
        return jsonify({"error": "Der geänderte Prompt darf nicht leer sein."}), 400
    if t.get('status') == 'laufend':
        return jsonify({"error": "Die Übersetzung läuft bereits."}), 409
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"error": "GEMINI_API_KEY fehlt in .env"}), 500
    try:
        batch_size = int(data.get('batch_size', t.get('batch_size', 40)))
        sync_offset = int(
            t.get('sync_offset', 0)
            if t.get('translation_started')
            else data.get('sync_offset', t.get('sync_offset', 0))
        )
    except (TypeError, ValueError):
        return jsonify({"error": "Ungültige Batch-Größe oder ungültiger Sync-Offset."}), 400
    if not 1 <= batch_size <= 500:
        return jsonify({"error": "Die Batch-Größe muss zwischen 1 und 500 liegen."}), 400
    translation_model = data.get('translation_model', t.get('translation_model') or t.get('gemini_model') or 'gemini-3.1-flash-lite')
    if translation_model not in GEMINI_MODEL_IDS:
        return jsonify({"error": "Ungültige Gemini-Modellauswahl."}), 400
    if not reset_translation_for_regeneration(t_id):
        return jsonify({"error": "Projekt kann derzeit nicht neu generiert werden."}), 409
    save_project_settings(t_id, {
        **t,
        'batch_size': batch_size,
        'sync_offset': sync_offset,
        'gemini_model': translation_model,
        'translation_model': translation_model,
    })

    base_name = t['original_filename'].replace('.srt', '')
    for suffix in ('_FA.srt', '_Vokabeln.csv', '_Interaktiv.ass'):
        output_file = os.path.join(current_app.config['OUTPUTS_DIR'], f'{base_name}{suffix}')
        if os.path.exists(output_file):
            os.remove(output_file)

    success = start_translation_job(
        t_id, api_key, current_app.config['UPLOADS_DIR'],
        current_app.config['OUTPUTS_DIR'], prompt_override=prompt
    )
    if not success:
        return jsonify({"error": "Neugenerierung konnte nicht gestartet werden."}), 409
    return jsonify({"message": "SRT-Neugenerierung gestartet"}), 202

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
from app.services.edtech_service import validate_csv_timestamps, validate_edtech_csv, fix_csv_timestamps, gemini_followup_fix_mismatches, generate_learning_subtitles
from app.prompt_manager import load_prompts, get_edtech_instruction

@main_bp.route('/api/edtech/validate/<int:t_id>', methods=['GET'])
def validate_edtech(t_id):
    t = get_translation_by_id(t_id)
    if not t: 
        return jsonify({"error": "Projekt nicht gefunden"}), 404
    
    farsi_srt = os.path.join(current_app.config['OUTPUTS_DIR'], t['original_filename'].replace('.srt', '_FA.srt'))
    german_srt = os.path.join(current_app.config['UPLOADS_DIR'], t['original_filename'])
    csv_file = os.path.join(current_app.config['OUTPUTS_DIR'], t['original_filename'].replace('.srt', '_Vokabeln.csv'))
    
    if not os.path.exists(farsi_srt):
        return jsonify({"error": "Farsi-SRT existiert noch nicht. Bitte zuerst übersetzen."}), 400
        
    if not os.path.exists(csv_file):
        return jsonify({"status": "no_csv_yet"})
        
    report = validate_edtech_csv(german_srt, farsi_srt, csv_file)
    
    return jsonify({
        "status": "validated",
        "ts_mismatches": report['ts_mismatches'],
        "kw_mismatches": report['kw_mismatches'],
        "data_issues": report['data_issues']
    })

@main_bp.route('/api/edtech/fix/<int:t_id>', methods=['POST'])
def fix_edtech(t_id):
    try:
        t = get_translation_by_id(t_id)
        if not t: 
            return jsonify({"error": "Projekt nicht gefunden"}), 404
            
        farsi_srt = os.path.join(current_app.config['OUTPUTS_DIR'], t['original_filename'].replace('.srt', '_FA.srt'))
        german_srt = os.path.join(current_app.config['UPLOADS_DIR'], t['original_filename'])
        csv_file = os.path.join(current_app.config['OUTPUTS_DIR'], t['original_filename'].replace('.srt', '_Vokabeln.csv'))
        
        if not os.path.exists(farsi_srt) or not os.path.exists(csv_file):
            return jsonify({"error": "Fehlende Dateien (SRT oder CSV) für die Reparatur."}), 400

        data = request.json or {}
        method = data.get('method')
        
        report = validate_edtech_csv(german_srt, farsi_srt, csv_file)
        rows = report['rows']
        fieldnames = report['fieldnames']
        ts_mismatches = report['ts_mismatches']
        kw_mismatches = report['kw_mismatches']
        data_issues = report['data_issues']
        
        if method == 'python' and ts_mismatches:
            fix_csv_timestamps(csv_file, rows, fieldnames, ts_mismatches)
            _, vocab_path = resolve_export_paths(t.get('profile_key', 'default'), t.get('episode_key', ''))
            copy_file_to_export(csv_file, vocab_path)
        elif method == 'gemini' and (kw_mismatches or data_issues):
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key: return jsonify({"error": "API Key fehlt"}), 500
            gemini_followup_fix_mismatches(
                api_key,
                farsi_srt,
                csv_file,
                kw_mismatches + data_issues,
                german_srt_path=german_srt,
                model=t.get('edtech_model') or t.get('gemini_model') or 'gemini-3.1-flash-lite'
            )
            _, vocab_path = resolve_export_paths(t.get('profile_key', 'default'), t.get('episode_key', ''))
            copy_file_to_export(csv_file, vocab_path)
        elif method == 'ignore':
            pass
        else:
            return jsonify({"error": "Unbekannte Methode oder keine Fehler für diese Methode gefunden"}), 400
            
        return jsonify({"message": f"Reparatur mit '{method}' ausgeführt"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def str_to_bool(v):
    """Konvertiert Strings wie 'false', '0' oder Checkbox 'on' sicher in Booleans."""
    if isinstance(v, bool): return v
    return str(v).lower() in ("yes", "true", "t", "1", "on")

@main_bp.route('/api/edtech/generate/<int:t_id>', methods=['POST'])
def generate_edtech(t_id):
    try:
        t = get_translation_by_id(t_id)
        if not t: 
            return jsonify({"error": "Projekt nicht gefunden"}), 404
            
        data = request.json or {}
        
        # Sicherstellen, dass fehlende Checkbox-Werte als 'False' gewertet werden!
        generate_csv_only = str_to_bool(data.get('generate_csv_only', False))
        force_csv_regeneration = str_to_bool(data.get('force_csv_regeneration', False))
        ignore_validation_errors = str_to_bool(data.get('ignore_validation_errors', False))
        hl_bold = str_to_bool(data.get('hl_bold', False))
        hl_underline = str_to_bool(data.get('hl_underline', False))
        hl_color = str_to_bool(data.get('hl_color', False))
        
        # Für Text/Zahlen greifen wir weiterhin auf DB-Defaults zurück, falls das Feld fehlt
        infobox_duration = int(data.get('infobox_duration', t.get('infobox_duration', 7)))
        sync_offset_ms = int(data.get('ass_sync_offset', t.get('ass_sync_offset', 0)))
        infobox_content = data.get('infobox_content', t.get('infobox_content', 'german_only'))
        episode_summary = data.get('episode_summary', t.get('episode_summary', ''))
        profile_key = data.get('profile_key', t.get('profile_key', 'default'))
        gemini_model = data.get('edtech_model', data.get('gemini_model', t.get('edtech_model') or t.get('gemini_model', 'gemini-3.1-flash-lite')))
        custom_edtech_prompt = data.get('custom_edtech_prompt', '').strip()

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
            , 'gemini_model': t.get('gemini_model') or t.get('translation_model', 'gemini-3.1-flash-lite')
            , 'translation_model': t.get('translation_model') or t.get('gemini_model', 'gemini-3.1-flash-lite')
            , 'edtech_model': gemini_model
        }
        save_project_settings(t_id, merged_settings)
        
        german_srt = os.path.join(current_app.config['UPLOADS_DIR'], t['original_filename'])
        farsi_srt = os.path.join(current_app.config['OUTPUTS_DIR'], t['original_filename'].replace('.srt', '_FA.srt'))
        ass_file = os.path.join(current_app.config['OUTPUTS_DIR'], t['original_filename'].replace('.srt', '_Interaktiv.ass'))
        csv_file = os.path.join(current_app.config['OUTPUTS_DIR'], t['original_filename'].replace('.srt', '_Vokabeln.csv'))

        if not generate_csv_only:
            if not os.path.exists(csv_file):
                return jsonify({"error": "CSV muss vor der ASS-Erstellung generiert werden."}), 409
            validation_report = validate_edtech_csv(german_srt, farsi_srt, csv_file)
            ts_mismatches = validation_report['ts_mismatches']
            kw_mismatches = validation_report['kw_mismatches']
            data_issues = validation_report['data_issues']
            if (ts_mismatches or kw_mismatches or data_issues) and not ignore_validation_errors:
                return jsonify({
                    "error": "CSV-Prüfung muss bestanden oder explizit ignoriert werden.",
                    "status": "validation_required",
                    "ts_mismatches": ts_mismatches,
                    "kw_mismatches": kw_mismatches,
                    "data_issues": data_issues
                }), 409
        
        prompts_data = load_prompts()
        custom_edtech = custom_edtech_prompt or get_edtech_instruction(
            prompts_data, merged_settings.get('profile_key', 'default')
        )
        
        res_ass, res_csv = generate_learning_subtitles(
            farsi_srt_path=farsi_srt,
            ass_filepath=ass_file,
            german_srt_path=german_srt,
            summary=merged_settings.get('episode_summary', ''),
            api_key=os.getenv("GEMINI_API_KEY"),
            custom_system_instruction=custom_edtech,
            generate_csv_only=generate_csv_only,
            force_csv_regeneration=force_csv_regeneration,
            infobox_duration=infobox_duration,
            highlight_bold=hl_bold,
            highlight_underline=hl_underline,
            highlight_color=hl_color,
            infobox_content=merged_settings.get('infobox_content', 'german_only'),
            sync_offset_ms=sync_offset_ms
            , model=gemini_model
        )
        
        if generate_csv_only:
            if res_csv and os.path.exists(res_csv):
                update_edtech_status(t_id, 0)
                _, vocab_path = resolve_export_paths(merged_settings.get('profile_key', 'default'), t.get('episode_key', ''))
                copy_file_to_export(res_csv, vocab_path)
                return jsonify({"message": "CSV erfolgreich generiert"})
            return jsonify({"error": "CSV generiert, Datei aber auf dem Laufwerk nicht gefunden"}), 500
        else:
            if res_ass and os.path.exists(res_ass) and res_csv and os.path.exists(res_csv):
                update_edtech_status(t_id, 1)
                subtitles_path, vocab_path = resolve_export_paths(merged_settings.get('profile_key', 'default'), t.get('episode_key', ''))
                copy_file_to_export(res_ass, subtitles_path)
                copy_file_to_export(res_csv, vocab_path)
                return jsonify({"message": "ASS und CSV erfolgreich generiert"})
            return jsonify({"error": "Generierung lief durch, aber Dateien fehlen auf dem Laufwerk"}), 500
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@main_bp.route('/api/project/<int:t_id>', methods=['GET'])
def get_project(t_id):
    """Liefert die Projektdaten und Settings für das Frontend."""
    t = get_translation_by_id(t_id)
    if not t:
        return jsonify({"error": "Projekt nicht gefunden"}), 404
    add_project_display_names(t)
    base_name = t['original_filename'].replace('.srt', '')
    outputs_dir = current_app.config['OUTPUTS_DIR']
    t['available_downloads'] = {
        'srt': os.path.exists(os.path.join(outputs_dir, f"{base_name}_FA.srt")),
        'ass': bool(t.get('edtech_done')) and os.path.exists(os.path.join(outputs_dir, f"{base_name}_Interaktiv.ass")),
        'csv': os.path.exists(os.path.join(outputs_dir, f"{base_name}_Vokabeln.csv"))
    }
    return jsonify(t)

@main_bp.route('/api/prompts/<int:t_id>', methods=['GET'])
def get_prompts(t_id):
    """Liefert die zusammengesetzten Prompts für die UI-Ansicht (Tabs)."""
    t = get_translation_by_id(t_id)
    if not t:
        return jsonify({"error": "Projekt nicht gefunden"}), 404
        
    episode_summary = t.get('episode_summary', '').strip()
    return jsonify(build_prompt_payload(
        t.get('profile_key', 'default'),
        episode_summary,
        t.get('custom_translation_prompt', '')
    ))

@main_bp.route('/api/edtech/preview/<int:t_id>', methods=['GET'])
def preview_edtech_files(t_id):
    t = get_translation_by_id(t_id)
    if not t: return jsonify({"error": "Projekt nicht gefunden"}), 404
    base = t['original_filename'].replace('.srt', '')
    srt_path = os.path.join(current_app.config['OUTPUTS_DIR'], f'{base}_FA.srt')
    original_srt_path = os.path.join(current_app.config['UPLOADS_DIR'], t['original_filename'])
    csv_path = os.path.join(current_app.config['OUTPUTS_DIR'], f'{base}_Vokabeln.csv')
    ass_path = os.path.join(current_app.config['OUTPUTS_DIR'], f'{base}_Interaktiv.ass')
    srt_text = ''
    if os.path.exists(srt_path):
        with open(srt_path, encoding='utf-8-sig', errors='replace') as f:
            srt_text = f.read()
    original_srt_text = ''
    if os.path.exists(original_srt_path):
        try:
            with open(original_srt_path, encoding='utf-8-sig') as f:
                original_srt_text = f.read()
        except UnicodeDecodeError:
            with open(original_srt_path, encoding='iso-8859-1') as f:
                original_srt_text = f.read()
    csv_rows = []
    csv_fieldnames = []
    if os.path.exists(csv_path):
        with open(csv_path, encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            csv_fieldnames = reader.fieldnames or []
            csv_rows = list(reader)
    ass_text = ''
    if os.path.exists(ass_path):
        with open(ass_path, encoding='utf-8') as f: ass_text = f.read()
    return jsonify({
        'srt': srt_text,
        'original_srt': original_srt_text,
        'ass_sync_offset_ms': t.get('ass_sync_offset', 0),
        'translation_sync_offset_ms': t.get('sync_offset', 0),
        'csv': csv_rows,
        'csv_fieldnames': csv_fieldnames,
        'ass': ass_text,
    })

@main_bp.route('/api/edtech/csv/<int:t_id>', methods=['POST'])
def save_edtech_csv(t_id):
    t = get_translation_by_id(t_id)
    if not t:
        return jsonify({'error': 'Projekt nicht gefunden'}), 404

    csv_path = os.path.join(
        current_app.config['OUTPUTS_DIR'],
        t['original_filename'].replace('.srt', '_Vokabeln.csv')
    )
    if not os.path.exists(csv_path):
        return jsonify({'error': 'CSV-Datei nicht gefunden'}), 404

    data = request.get_json(silent=True) or {}
    rows = data.get('rows')
    if not isinstance(rows, list) or len(rows) > 10000:
        return jsonify({'error': 'Ungültige CSV-Zeilendaten.'}), 400

    with open(csv_path, encoding='utf-8-sig', newline='') as csv_file:
        fieldnames = csv.DictReader(csv_file).fieldnames or []
    if not fieldnames:
        return jsonify({'error': 'CSV-Datei enthält keine Spaltenüberschriften.'}), 400

    saved_rows = []
    for row in rows:
        if not isinstance(row, dict) or set(row) - set(fieldnames):
            return jsonify({'error': 'CSV-Zeile hat ein ungültiges Format.'}), 400
        saved_row = {}
        for fieldname in fieldnames:
            value = row.get(fieldname, '')
            if value is None:
                value = ''
            if not isinstance(value, str):
                return jsonify({'error': 'CSV-Zellen müssen Textwerte enthalten.'}), 400
            saved_row[fieldname] = value
        saved_rows.append(saved_row)

    temporary_csv = f'{csv_path}.tmp'
    try:
        with open(temporary_csv, 'w', encoding='utf-8-sig', newline='') as csv_file:
            writer = csv.DictWriter(
                csv_file, fieldnames=fieldnames, quoting=csv.QUOTE_ALL
            )
            writer.writeheader()
            writer.writerows(saved_rows)
        os.replace(temporary_csv, csv_path)
    finally:
        if os.path.exists(temporary_csv):
            os.remove(temporary_csv)

    return jsonify({'message': 'CSV gespeichert.', 'row_count': len(saved_rows)})

@main_bp.route('/api/prompts/preview', methods=['GET', 'POST'])
def preview_prompts():
    data = request.get_json(silent=True) or {}
    profile_key = data.get('profile_key', request.args.get('profile_key', 'default'))
    episode_key = data.get('episode', request.args.get('episode', ''))
    episode_summary = (
        data.get('episode_summary', request.args.get('episode_summary', '')).strip()
        if episode_key == '__custom__'
        else get_episode_summary(profile_key, episode_key)
    )
    return jsonify(build_prompt_payload(profile_key, episode_summary))

@main_bp.route('/api/download/<int:t_id>', methods=['GET'])
def download_file(t_id):
    """Liefert die fertig generierten Dateien aus."""
    t = get_translation_by_id(t_id)
    if not t:
        return jsonify({"error": "Projekt nicht gefunden"}), 404
        
    file_type = request.args.get('type')
    base_name = t['original_filename'].replace('.srt', '')
    
    if file_type == 'srt':
        path = os.path.join(current_app.config['OUTPUTS_DIR'], f"{base_name}_FA.srt")
    elif file_type == 'ass':
        path = os.path.join(current_app.config['OUTPUTS_DIR'], f"{base_name}_Interaktiv.ass")
    elif file_type == 'csv':
        path = os.path.join(current_app.config['OUTPUTS_DIR'], f"{base_name}_Vokabeln.csv")
    else:
        return jsonify({"error": "Ungültiger Dateityp"}), 400
        
    if os.path.exists(path):
        return send_file(path, as_attachment=True)
    return jsonify({"error": "Datei existiert noch nicht"}), 404
@main_bp.route('/api/metadata', methods=['GET'])
def get_metadata():
    """Liest prompts.yaml und summaries.yaml aus und liefert sie für die UI-Dropdowns."""
    base_dir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    prompts_path = os.path.join(base_dir, 'prompts.yaml')
    summaries_path = os.path.join(base_dir, 'summaries.yaml')
    
    prompts_data = {}
    summaries_data = {}
    
    try:
        if os.path.exists(prompts_path):
            with open(prompts_path, 'r', encoding='utf-8') as f:
                prompts_data = yaml.safe_load(f) or {}
        if os.path.exists(summaries_path):
            with open(summaries_path, 'r', encoding='utf-8') as f:
                summaries_data = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"YAML Parse Fehler: {e}")

    profiles = {}
    # Baue eine Liste aller Profile (außer 'default', das dient nur als Fallback)
    for key, data in prompts_data.items():
        profiles[key] = {
            "name": data.get("label", data.get("name", key.capitalize())),
            "episodes": list(summaries_data.get(key, {}).keys()) if key in summaries_data else []
        }
            
    return jsonify({"profiles": profiles, "summaries": summaries_data})