"""Standalone editor authentication; never trust identity headers from a client."""
import secrets
import time

from flask import abort, current_app, redirect, render_template_string, request, session, url_for
from werkzeug.security import check_password_hash

LOGIN = '''<!doctype html><html lang="de"><title>Redaktion anmelden</title>
<h1>Redaktion anmelden</h1><p>{{ error }}</p><form method="post">
<input type="hidden" name="csrf_token" value="{{ csrf }}">
<label>Name <input name="username" autocomplete="username" required></label>
<label>Passwort <input type="password" name="password" autocomplete="current-password" required></label>
<button>Anmelden</button></form></html>'''


def install_editor_auth(app):
    def csrf_token():
        if 'editor_csrf' not in session:
            session['editor_csrf'] = secrets.token_urlsafe(32)
        return session['editor_csrf']

    def check_csrf():
        expected = session.get('editor_csrf', '')
        supplied = request.form.get('csrf_token', '')
        if not expected or not secrets.compare_digest(expected, supplied):
            abort(403)

    app.jinja_env.globals['csrf_token'] = csrf_token

    @app.before_request
    def protect_editor():
        if request.path == '/review' or request.path.startswith('/review/'):
            if (session.get('editor') != current_app.config.get('EDITOR_USERNAME')
                    or not session.get('editor') or session.get('editor_expires', 0) <= time.time()):
                abort(401)
            if request.method not in ('GET', 'HEAD', 'OPTIONS'):
                check_csrf()

    @app.route('/editor/login', methods=['GET', 'POST'])
    def editor_login():
        error = ''
        if request.method == 'POST':
            check_csrf()
            username = current_app.config.get('EDITOR_USERNAME', '')
            password_hash = current_app.config.get('EDITOR_PASSWORD_HASH', '')
            if (username and password_hash
                    and secrets.compare_digest(request.form.get('username', ''), username)
                    and check_password_hash(password_hash, request.form.get('password', ''))):
                session.clear()
                session.update(editor=username, editor_expires=time.time() + 3600)
                return redirect('/review')
            error = 'Anmeldung fehlgeschlagen.'
        return render_template_string(LOGIN, error=error, csrf=csrf_token()), (401 if error else 200)

    @app.post('/editor/logout')
    def editor_logout():
        check_csrf()
        session.clear()
        return redirect(url_for('editor_login'))
