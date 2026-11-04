# Grundschul-Wörterbuch

Ein kindgerechtes Wörterbuch für die Grundschule – lokal lauffähig, auf Flask und SQLite aufgebaut. Worteinträge werden mit KI generiert und enthalten Silben, Rechtschreibstrategien, Wortfamilien, Übersetzungen und grammatische Formen.

<!-- schulplattform:installation -->
## Installation

### Im Rahmen der Schulplattform

Empfohlen für den Schulserver: Die [Schulplattform](https://github.com/Bingenberger/schulplattform) installiert diese App zusammen mit den
anderen Schul-Apps auf einem leeren Ubuntu-24.04-Server, mit eigener Subdomain, TLS-Zertifikat, Mailversand,
Sicherung und Dashboard. Sie verwendet das signierte Release-Image `ghcr.io/bingenberger/gswb`
und die unveränderte `docker-compose.yml` dieses Repositorys plus eine Override-Datei.

1. In der Plattformkonfiguration (`./install.sh configure` bzw. `/etc/schulplattform/platform.toml`)
   unter `[apps.gswb]` `enabled = true` und den Hostnamen setzen, z. B. `woerterbuch.ihre-schule.de`,
   und beim DNS-Provider einen A-Eintrag auf den Server anlegen.
2. `./install.sh apply …` installiert die App. Migration, Proxy, Zertifikat und Sicherung übernimmt die Plattform.
3. `./install.sh app-setup gswb` legt den Redaktionszugang an (Benutzername und Passwort am Terminal; gespeichert wird nur ein Werkzeug-Hash). Ohne diesen Schritt bleibt die Redaktion geschlossen, die öffentliche Suche funktioniert trotzdem.
4. Daten vom bisherigen Server übernehmen: `./install.sh import gswb …` nach dem
   [Umzugs-Runbook](https://github.com/Bingenberger/schulplattform/blob/main/docs/betrieb/umzug.md).

### Standalone mit Docker Compose

Ohne Plattform, z. B. zum Ausprobieren oder für einen eigenen Server mit eigenem Proxy.
Benötigt Docker Engine mit Compose v2 (amd64). Die App lauscht danach nur auf `http://127.0.0.1:8005`.

```sh
mkdir -m 700 .private
python3 -c "import secrets;print(secrets.token_urlsafe(48))" > .private/session-key
: > .private/editor-hash              # leer = Redaktion geschlossen
chmod 444 .private/session-key .private/editor-hash
export GSWB_SECRET_FILE="$PWD/.private/session-key" GSWB_EDITOR_HASH_FILE="$PWD/.private/editor-hash"
docker compose build
docker compose run --rm app python -m grundschul_woerterbuch.migrate
docker compose up -d
```

Für die Redaktion `EDITOR_USERNAME` setzen und einen Werkzeug-Passworthash in die Hashdatei schreiben
(Details in [PLATFORM.md](PLATFORM.md)). Wortdaten, Bilder und Audio sind nicht im Image enthalten
(siehe „Datenbank aufbauen“ und „Medien-Dateien“).

Statt selbst zu bauen, kann das veröffentlichte Image verwendet werden (dann `docker compose build` weglassen):

```sh
docker pull ghcr.io/bingenberger/gswb:0.1.0 && docker tag ghcr.io/bingenberger/gswb:0.1.0 gswb:0.1.0-dev
```
<!-- /schulplattform:installation -->

## Was das Wörterbuch kann

- **Fehlertolerante Suche** – exakte Treffer, Präfixsuche, Fehlschreibungen und unscharfe Suche (rapidfuzz), Autocomplete per JSON-API
- **Wortseiten** mit Silbendarstellung (farbig), Wortart-Kennzeichnung, Bild und Audio
- **Rechtschreibung** – Kategorien mit Symbolen, Strategie-Text, häufige Fehlschreibungen
- **Wortfamilien** als Hub-and-Spoke-Visualisierung, Wortfelder, Synonyme
- **Grammatik** – Deklination (Nomen), Konjugation (Verb), Steigerung (Adjektiv)
- **Übersetzungen** in Englisch, Französisch, Türkisch und Arabisch
- **Rechtschreibkategorien** durchsuchbar – alle Wörter einer Kategorie auf einen Blick
- **Wort des Tages** auf der Startseite
- **Schreibproben-Analyse** – Foto hochladen, Fehler markieren lassen (Gemini Vision)
- **Suchfeld im Header** auf allen Wortseiten

Aktuell in der Datenbank: **5.814 Wörter** in allen 11 deutschen Wortarten.

## Projektstruktur

```
grundschul_woerterbuch/   # Flask-App (Factory, Routen, Services, Repository)
templates/                # Jinja2-Templates
static/
  css/styles.css          # Alle Styles
  js/app.js               # Autocomplete, Schreibprobe, Review-Shortcuts
  images/                 # Wortbilder (*.webp, nicht im Repo)
  audio/                  # Symlink → ../audio/ (nicht im Repo)
  rs_icons/               # SVG-Symbole für Rechtschreibkategorien
  fonts/                  # Grundschrift, Fredoka
  vendor/phosphor/        # Phosphor-Icons
data/
  import_words/           # JSON-Quelldaten (eine Datei pro Wort)
  grundschul_woerterbuch.sqlite3   # Generierte Datenbank (nicht im Repo)
scripts/
  import_words.py         # JSON → SQLite (--rebuild)
  generate_words_with_claude.py   # Wortgenerierung via Anthropic API
  generate_words_with_gemini.py   # Wortgenerierung via Vertex AI / Gemini
  check_word_types_with_gemini.py # Wortarten-Prüfung bestehender JSONs
audio/                    # MP3-Dateien (nicht im Repo)
illustrationen/           # Quell-PNGs (nicht im Repo)
```

## Lokale Entwicklung (nativ)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## App starten

```bash
export SECRET_KEY=$(python3 -c "import secrets;print(secrets.token_urlsafe(48))")
python -m grundschul_woerterbuch.migrate     # Schema anlegen bzw. prüfen (nicht mehr automatisch beim Start)
SESSION_COOKIE_SECURE=0 flask --app app run --debug
```

Die App läuft dann unter `http://127.0.0.1:5005/` (Port via `.flaskenv`).

## Datenbank aufbauen

Die JSON-Dateien in `data/import_words/` sind die Quelldaten. Aus ihnen wird die SQLite-Datenbank generiert:

```bash
python3 scripts/import_words.py --rebuild
```

Das Schema legt `python -m grundschul_woerterbuch.migrate` an; beim App-Start geschieht das nicht mehr. Nach einem `--rebuild` invalidiert das Skript den Such-Cache automatisch.

Wenn Beziehungen auf noch nicht vorhandene Wörter verweisen, landen diese in:
- `data/missing_relation_words.txt` – alle fehlenden Zielwörter
- `data/missing_relation_words_next.txt` – priorisiert für den nächsten Generierungslauf
- `data/missing_relation_report.json` – strukturierter Bericht mit Häufigkeiten

## Wörter generieren

### Mit Claude (Anthropic API)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python3 scripts/generate_words_with_claude.py woerterliste.txt --skip-existing
```

Für große Mengen empfiehlt sich der Batch-Modus (50 % Rabatt, asynchron):

```bash
python3 scripts/generate_words_with_claude.py woerterliste.txt --batch
```

Einen abgeschlossenen Batch nachträglich abrufen:

```bash
python3 scripts/generate_words_with_claude.py --resume-batch msgbatch_...
```

Nützliche Optionen:

| Option | Bedeutung |
|---|---|
| `--skip-existing` | Wörter überspringen, für die im Importordner schon eine JSON-Datei liegt |
| `--overwrite-json` | Vorhandene JSON-Dateien neu erzeugen |
| `--dry-run` | Nur JSON erzeugen, nicht in SQLite importieren |
| `--model claude-sonnet-4-6` | Modell wählen (Standard: `claude-sonnet-4-6`) |
| `--batch` | Anthropic Batch API nutzen |
| `--resume-batch BATCH_ID` | Ergebnis eines abgeschlossenen Batches abrufen |

### Mit Gemini (Vertex AI)

```bash
python3 scripts/generate_words_with_gemini.py woerterliste.txt --credentials-file key.json --skip-existing
```

Wortarten bestehender JSONs prüfen und ggf. korrigieren:

```bash
python3 scripts/check_word_types_with_gemini.py --credentials-file key.json
python3 scripts/check_word_types_with_gemini.py --credentials-file key.json --apply
```

## Medien-Dateien

Die App erwartet Bilder und Audio unter diesen Pfaden (jeweils nicht im Repo):

| Pfad | Inhalt |
|---|---|
| `static/images/WORT.webp` | Wortbild (WebP) |
| `audio/WORT.mp3` | Aussprache (MP3) |

`static/audio` ist ein Symlink auf `../audio/`. Beim Einrichten nach einem Clone:

```bash
# Symlink anlegen (audio/-Ordner muss vorhanden sein)
ln -s ../audio static/audio
```

Quell-PNGs aus `illustrationen/` lassen sich mit `cwebp` konvertieren:

```bash
find illustrationen/ -name "*.png" \
  | xargs -P8 -I{} bash -c '
      stem=$(basename "$1" .png)
      cwebp -q 85 "$1" -o "static/images/${stem}.webp" -quiet
    ' _ {}
```

## Schreibproben-Analyse

Unter `/writing-check` können Kinder Fotos ihrer Schreibproben hochladen. Gemini Vision erkennt Fehler und ordnet sie Wörterbucheinträgen zu.

```bash
# Gemini-Modus (Vertex AI key.json erforderlich)
export HANDWRITING_MODE=gemini

# Mock-Modus (kein API-Schlüssel nötig)
export HANDWRITING_MODE=mock
```

Die App erkennt Credentials automatisch in `./key.json`, `./key3.json`, `./scripts/key.json` und `./scripts/key3.json`.

## Konfiguration

Alle Einstellungen per Umgebungsvariable:

| Variable | Standard | Bedeutung |
|---|---|---|
| `HANDWRITING_MODE` | `gemini` | `gemini` oder `mock` |
| `GEMINI_CREDENTIALS_FILE` | `./key.json` | Vertex-AI-Service-Account |

## Server-Installation (Produktion)

> **Historischer nativer Weg.** Empfohlen sind die Plattform oder Docker Compose (siehe „Installation“).
> Wer nativ installiert, muss zusätzlich `SECRET_KEY` (mindestens 32 Zeichen) setzen und vor dem ersten
> Start `python -m grundschul_woerterbuch.migrate` ausführen; ohne Redaktionskonfiguration bleibt `/editor` geschlossen.

> **Historischer nativer Weg.** Empfohlen sind die Plattform oder Docker Compose (siehe „Installation“).
> Wer nativ installiert, muss zusätzlich `SECRET_KEY` (mindestens 32 Zeichen) setzen und vor dem ersten
> Start `python -m grundschul_woerterbuch.migrate` ausführen; ohne Redaktionskonfiguration bleibt `/editor` geschlossen.

Die folgende Anleitung richtet sich an einen Ubuntu/Debian-Server mit nginx. Als WSGI-Server wird Gunicorn verwendet (in `requirements.txt` enthalten).

### 1. Voraussetzungen installieren

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip nginx git
```

### 2. Projektdateien auf den Server bringen

```bash
# Repository klonen
git clone https://github.com/DEIN-NAME/grundschul-woerterbuch.git /var/www/grundschul-woerterbuch
cd /var/www/grundschul-woerterbuch

# Python-Umgebung einrichten
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Mediendateien übertragen

Bilder und Audio sind nicht im Repository und müssen separat auf den Server übertragen werden:

```bash
# Vom lokalen Rechner ausführen:
rsync -avz --progress static/images/ user@server:/var/www/grundschul-woerterbuch/static/images/
rsync -avz --progress audio/          user@server:/var/www/grundschul-woerterbuch/audio/
```

Dann auf dem Server den Audio-Symlink anlegen:

```bash
cd /var/www/grundschul-woerterbuch
ln -s ../audio static/audio
```

### 4. Datenbank aufbauen

```bash
cd /var/www/grundschul-woerterbuch
source venv/bin/activate
python3 scripts/import_words.py --rebuild
```

### 5. Umgebungsvariablen konfigurieren

Datei `/var/www/grundschul-woerterbuch/.env` anlegen:

```env
HANDWRITING_MODE=gemini
GEMINI_CREDENTIALS_FILE=/var/www/grundschul-woerterbuch/key.json
```

Für den Mock-Modus (kein API-Schlüssel nötig):

```env
HANDWRITING_MODE=mock
```

### 6. systemd-Service einrichten

Datei `/etc/systemd/system/grundschul-woerterbuch.service` anlegen:

```ini
[Unit]
Description=Grundschul-Wörterbuch
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/grundschul-woerterbuch
EnvironmentFile=/var/www/grundschul-woerterbuch/.env
ExecStart=/var/www/grundschul-woerterbuch/venv/bin/gunicorn \
    --workers 2 \
    --bind 127.0.0.1:5005 \
    --access-logfile /var/log/grundschul-woerterbuch/access.log \
    --error-logfile  /var/log/grundschul-woerterbuch/error.log \
    app:app
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Log-Verzeichnis anlegen und Service starten:

```bash
sudo mkdir -p /var/log/grundschul-woerterbuch
sudo chown www-data:www-data /var/log/grundschul-woerterbuch
sudo chown -R www-data:www-data /var/www/grundschul-woerterbuch

sudo systemctl daemon-reload
sudo systemctl enable grundschul-woerterbuch
sudo systemctl start grundschul-woerterbuch

# Status prüfen
sudo systemctl status grundschul-woerterbuch
```

### 7. nginx als Reverse Proxy

Datei `/etc/nginx/sites-available/grundschul-woerterbuch` anlegen:

```nginx
server {
    listen 80;
    server_name meinserver.example.com;

    # Statische Dateien direkt über nginx ausliefern (schneller als Gunicorn)
    location /static/ {
        alias /var/www/grundschul-woerterbuch/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Audio direkt aus dem audio/-Ordner ausliefern
    location /static/audio/ {
        alias /var/www/grundschul-woerterbuch/audio/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Alles andere an Gunicorn weiterleiten
    location / {
        proxy_pass         http://127.0.0.1:5005;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}
```

Site aktivieren und nginx neu laden:

```bash
sudo ln -s /etc/nginx/sites-available/grundschul-woerterbuch \
           /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 8. HTTPS einrichten (empfohlen)

Mit Certbot und Let's Encrypt:

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d meinserver.example.com
```

Certbot passt die nginx-Konfiguration automatisch an und richtet die automatische Zertifikatserneuerung ein.

### Wartung

```bash
# App nach Code-Änderungen neu starten
sudo systemctl restart grundschul-woerterbuch

# Datenbank nach neuen Wortdaten neu aufbauen
cd /var/www/grundschul-woerterbuch
source venv/bin/activate
python3 scripts/import_words.py --rebuild
sudo systemctl restart grundschul-woerterbuch

# Logs einsehen
sudo journalctl -u grundschul-woerterbuch -f
```

## Rechtschreibkategorien

Das Wörterbuch kennt 12 Rechtschreibkategorien, jede mit eigenem SVG-Symbol in `static/rs_icons/`:

| Kategorie | Symbol |
|---|---|
| Bausteinwort | Symbol Baustein.svg |
| Mitsprechwort | Symbol Mitsprechwort.svg |
| Wort mit Kürzezeichen | Symbol Kürzezeichen.svg |
| Ableitungswort | Symbol Ableitung.svg |
| Verlängerungswort | Symbol Verlängern.svg |
| Merkwort mit ie / Dehnungs-h / V / ß / X / Qu / doppeltem Vokal | Symbol Merkwort.svg |
| Großschreibung | Symbol Großschreibung.svg |
