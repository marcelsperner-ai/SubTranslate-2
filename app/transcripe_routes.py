import sqlite3

from flask import Blueprint, current_app, jsonify, request

from app.db import save_default_settings
from app.services.transcripe_service import (
    get_transcripe_settings, project_import_info, record_event, validate_settings,
)


transcripe_bp = Blueprint('transcripe', __name__, url_prefix='/api/transcripe')


@transcripe_bp.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'GET':
        return jsonify(get_transcripe_settings())
    try:
        values = validate_settings(request.get_json(silent=True))
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    save_default_settings('transcripe', values)
    if values['enabled']:
        current_app.extensions['transcripe'].start()
    return jsonify(values)


@transcripe_bp.route('/status')
def status():
    return jsonify(current_app.extensions['transcripe'].status())


@transcripe_bp.route('/project/<int:translation_id>')
def project_info(translation_id):
    return jsonify(project_import_info(translation_id))


@transcripe_bp.route('/scan', methods=['POST'])
def scan():
    try:
        current_app.extensions['transcripe'].scan()
    except (OSError, ValueError, sqlite3.Error) as error:
        current_app.logger.exception('Transcripe-Scan fehlgeschlagen')
        record_event('watcher', 'error', str(error))
        return jsonify({'error': str(error)}), 400
    return jsonify(current_app.extensions['transcripe'].status())


@transcripe_bp.route('/launch', methods=['POST'])
def launch():
    try:
        url = current_app.extensions['transcripe'].launch()
    except (OSError, ValueError) as error:
        current_app.logger.error('Transcripe-Start: %s', error)
        record_event('launcher', 'error', str(error))
        return jsonify({'error': str(error)}), 400
    record_event('launcher', 'success', 'Transcripe ist erreichbar.')
    return jsonify({'url': url})
