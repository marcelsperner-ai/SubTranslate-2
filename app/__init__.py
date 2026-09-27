import os
from datetime import datetime, timedelta
import time
from flask import Flask
from app.db import init_db, get_db_connection

def create_app():
    app = Flask(__name__)
    
    base_dir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    app.config['UPLOADS_DIR'] = os.path.join(base_dir, 'uploads')
    app.config['OUTPUTS_DIR'] = os.path.join(base_dir, 'outputs')
    
    os.makedirs(app.config['UPLOADS_DIR'], exist_ok=True)
    os.makedirs(app.config['OUTPUTS_DIR'], exist_ok=True)
    
    init_db()
    
    with app.app_context():
        reset_orphaned_jobs()
        
    from app.routes import main_bp
    app.register_blueprint(main_bp)
    
    return app

def reset_orphaned_jobs():
    """Setzt Jobs zurück, deren Heartbeat seit über 10 Minuten nicht erneuert wurde."""
    conn = get_db_connection()
    c = conn.cursor()
    
    timeout_threshold = time.time() - 600  # 10 Minuten in Sekunden
    
    c.execute('''
        UPDATE translations 
        SET status = 'pausiert', worker_token = NULL 
        WHERE status = 'laufend' AND heartbeat_at < ?
    ''', (timeout_threshold,))
    
    if c.rowcount > 0:
        print(f"🔧 Startup-Recovery: {c.rowcount} verwaiste Jobs (Timeout) auf 'pausiert' zurückgesetzt.")
        
    conn.commit()
    conn.close()