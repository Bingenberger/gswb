from pathlib import Path
import sqlite3
from flask import jsonify


def install_health(app):
    @app.get('/health/live')
    def live():
        return jsonify(status='alive')

    @app.get('/health/ready')
    def ready():
        try:
            uri = Path(app.config['DATABASE']).resolve().as_uri() + '?mode=ro'
            with sqlite3.connect(uri, uri=True, timeout=1) as db:
                if db.execute('PRAGMA user_version').fetchone()[0] != 1:
                    return jsonify(status='not-ready'), 503
                db.execute('SELECT id FROM words LIMIT 1').fetchall()
        except sqlite3.Error:
            return jsonify(status='not-ready'), 503
        return jsonify(status='ready')
