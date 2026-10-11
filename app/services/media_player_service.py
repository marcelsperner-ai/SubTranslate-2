import os
from pathlib import Path
import shutil
import subprocess

from app.db import get_translation_by_id
from app.services.transcripe_service import project_import_info


def _stored_file(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Mediendatei liegt ausserhalb der Projektablage.')
    if not path.is_file():
        raise FileNotFoundError(f'Datei nicht vorhanden: {path.name}')
    return path


def find_vlc() -> str:
    configured = os.environ.get('SUBTRANSLATE_VLC_PATH')
    if configured:
        path = Path(configured)
        if not path.is_file():
            raise FileNotFoundError('SUBTRANSLATE_VLC_PATH verweist nicht auf eine VLC-Datei.')
        return str(path.resolve())
    executable = shutil.which('vlc')
    if executable:
        return executable
    for variable in ('ProgramFiles', 'ProgramFiles(x86)'):
        directory = os.environ.get(variable)
        if directory:
            candidate = Path(directory) / 'VideoLAN' / 'VLC' / 'vlc.exe'
            if candidate.is_file():
                return str(candidate)
    raise FileNotFoundError(
        'VLC wurde nicht gefunden. VLC installieren oder SUBTRANSLATE_VLC_PATH '
        'auf den vollstaendigen Pfad zu vlc.exe setzen und SubTranslate neu starten.'
    )


def play_project(translation_id: int, uploads_dir: str, outputs_dir: str) -> str:
    project = get_translation_by_id(translation_id)
    if not project:
        raise FileNotFoundError('Projekt nicht gefunden.')
    imported = project_import_info(translation_id)
    if not imported or not imported['assets'].get('video'):
        raise FileNotFoundError('Fuer dieses Projekt ist noch kein Video aus Transcripe gespeichert.')
    video = _stored_file(Path(uploads_dir), imported['assets']['video'])
    base_name = project['original_filename'].replace('.srt', '')
    ass = Path(outputs_dir) / f'{base_name}_Interaktiv.ass'
    subtitle_type = 'ass' if project.get('edtech_done') and ass.is_file() else 'srt'
    subtitle_name = f'{base_name}_Interaktiv.ass' if subtitle_type == 'ass' else f'{base_name}_FA.srt'
    subtitle = _stored_file(Path(outputs_dir), subtitle_name)
    process = subprocess.Popen([
        find_vlc(), '--no-one-instance', '--no-sub-autodetect-file',
        '--subsdec-encoding=UTF-8', f'--sub-file={subtitle}', '--', str(video),
    ])
    try:
        code = process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        return subtitle_type
    raise OSError(f'VLC wurde unmittelbar beendet (Exit-Code {code}).')
