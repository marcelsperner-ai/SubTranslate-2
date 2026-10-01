import os
import shutil


def copy_file_to_export(file_path, target_dir, log_callback=None):
    """Kopiert eine fertige Datei zusätzlich in den konfigurierten Export-Ordner (überschreibt vorhandene Kopien)."""
    if not target_dir or not file_path or not os.path.exists(file_path):
        return
    try:
        os.makedirs(target_dir, exist_ok=True)
        shutil.copy2(file_path, os.path.join(target_dir, os.path.basename(file_path)))
    except OSError as e:
        message = f"⚠️ Export-Kopie nach '{target_dir}' fehlgeschlagen: {e}"
        if log_callback:
            log_callback(message)
        else:
            print(message)
