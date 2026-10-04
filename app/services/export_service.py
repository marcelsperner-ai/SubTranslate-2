import os
import shutil


def copy_file_to_export(file_path, target_dir, log_callback=None, export_options=None):
    """Kopiert eine fertige Datei mit optional angepasstem Namen in den Export-Ordner."""
    if not target_dir or not file_path or not os.path.exists(file_path):
        return False

    options = export_options or {}
    if options.get('skip'):
        return False

    target_filename = options.get('filename') or os.path.basename(file_path)
    if (
        not isinstance(target_filename, str)
        or target_filename in {'.', '..'}
        or os.path.basename(target_filename) != target_filename
        or '\\' in target_filename
    ):
        raise ValueError('Der Export-Dateiname darf keinen Pfad enthalten.')
    source_extension = os.path.splitext(file_path)[1]
    target_extension = os.path.splitext(target_filename)[1]
    if not target_extension:
        target_filename += source_extension
    elif target_extension.casefold() != source_extension.casefold():
        raise ValueError(f'Die Dateiendung muss {source_extension} bleiben.')

    target_path = os.path.join(target_dir, target_filename)
    try:
        os.makedirs(target_dir, exist_ok=True)
        if os.path.exists(target_path) and not options.get('overwrite', False):
            message = f"⚠️ Export-Kopie '{target_path}' besteht bereits und wurde nicht überschrieben."
            if log_callback:
                log_callback(message)
            else:
                print(message)
            return False
        shutil.copy2(file_path, target_path)
        return True
    except OSError as e:
        message = f"⚠️ Export-Kopie nach '{target_dir}' fehlgeschlagen: {e}"
        if log_callback:
            log_callback(message)
        else:
            print(message)
        return False
