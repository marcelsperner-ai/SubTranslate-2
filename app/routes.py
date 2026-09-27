import os
from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename
import pysrt
from dotenv import load_dotenv

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

@main_bp.route('/api/upload', methods=['POST'])
def upload_file():
    """Nimmt eine SRT entgegen und legt ein pausiertes Projekt an."""
    if 'file' not in request.files:
        return jsonify({"error": "Keine Datei hochgeladen"}), 400
        
    file = request.files['file']
    profile_key = request.form.get('profile_key', 'default')
    sync_offset = int(request.form.get('sync_offset', 0))
    
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