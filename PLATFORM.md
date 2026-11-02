# Sicherheits- und Containeränderungen

Entwicklungsstand; kein freigegebenes Plattformrelease.

`SECRET_KEY` (mindestens 32 zufällige Zeichen) bzw. `SECRET_KEY_FILE` ist Pflicht.
Die Redaktion verwendet vorerst eine lokale Anmeldung unter `/editor/login`:
`EDITOR_USERNAME` und `EDITOR_PASSWORD_HASH` (Werkzeug-Passworthash) bzw.
`EDITOR_PASSWORD_HASH_FILE`. Ohne Redaktionskonfiguration bleibt sie geschlossen.
Identitätsheader bewirken keine Anmeldung. Öffentliche Lese-APIs bleiben zugänglich.
Sitzung: eine Stunde; schreibende Redaktionsanfragen benötigen CSRF-Token.
Cookies sind standardmäßig HTTPS-only; nur lokale Tests verwenden
`SESSION_COOKIE_SECURE=0`. Das ersetzt noch keine Nextcloud-/BFF-Anbindung.

Standalone-Compose:

1. Secretdateien außerhalb von Git erstellen, für UID 10001 lesbar machen,
   Hostzugriff durch ein privates übergeordnetes Verzeichnis begrenzen.
2. `GSWB_SECRET_FILE` und `GSWB_EDITOR_HASH_FILE` auf diese Dateien setzen.
   Eine leere Hashdatei sperrt den Redaktionslogin.
3. `docker compose build`
4. `docker compose run --rm app python -m grundschul_woerterbuch.migrate`
5. `docker compose up -d`

Migrationen laufen nicht mehr bei jedem Appstart. Für lokale Pythonstarts ebenfalls
vorher `python -m grundschul_woerterbuch.migrate` ausführen. Tests dürfen ausdrücklich
`AUTO_INIT_DB=True` setzen. `/health/live` prüft den Prozess, `/health/ready` die
SQLite-Datenbank und Schema-Version 1, ohne KI oder SMTP anzusprechen.

Das Image enthält keine generierten Wortdaten, Audios, Bilder oder Zugangsschlüssel.
Der Standard `HANDWRITING_MODE=mock` in Compose dient ausschließlich Tests und ist
kein Ersatz für eine echte Handschrifterkennung. Daten, Bilder, Audio und Uploads
liegen in getrennten Volumes. Die App lauscht standalone nur auf Host-Loopback.

Offen: Freigabe/SBOM, Registry-Digest, vollständiger Backup-/Restore einschließlich
Medien, TLS-/Domain-Rollback, Schutz vor Login-Bruteforce, Plattformabnahme.
