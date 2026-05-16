# Grundschul-Wörterbuch

Ein erster, lokal startbarer Flask-Prototyp für ein kindgerechtes Wörterbuch mit Textsuche, vorbereiteter Spracheingabe, Schreibproben-Prototyp und SQLite als Hauptdatenquelle.

## Was der Prototyp kann

- reduzierte Startseite mit Suchfeld und Aufnahmebutton
- Textsuche mit exakter, normalisierter, fehlerrobuster und unscharfer Suche
- Autocomplete-Vorschlaege ueber einen JSON-Endpunkt
- Wortseiten mit Silbendarstellung, Silbenboegen, Erklaerung, Uebersetzungen, Beziehungen und grammatischen Formen
- Schreibproben-Prototyp mit Bild-Upload, Fehler-Markern und Zwei-Klick-Hinweisen
- SQLite-Datenbank als Hauptquelle
- JSON-Import fuer Beispieldaten
- vorbereitete Speech-Service-Schnittstelle mit Mock-Modus fuer spaetere whisper.cpp-Anbindung

## Projektstruktur

- `app.py`: Flask-Startpunkt
- `grundschul_woerterbuch/`: Anwendungscode
- `templates/`: Jinja2-Templates
- `static/`: CSS, JavaScript und Platzhalter-Bild
- `data/import_words/`: Beispiel-JSON-Dateien pro Wort
- `scripts/import_words.py`: Importskript fuer SQLite

## Installation

1. Virtuelle Umgebung anlegen und aktivieren:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Abhaengigkeiten installieren:

```bash
pip install -r requirements.txt
```

Falls die virtuelle Umgebung schon vorher erstellt wurde, bitte die Abhaengigkeiten nach der Aenderung noch einmal aktualisieren:

```bash
pip install -r requirements.txt
```

## Datenbank initialisieren und Beispieldaten importieren

Die Datenbank wird beim Start der App angelegt, falls sie noch nicht existiert. Die Beispieldaten importierst du so:

```bash
python3 scripts/import_words.py --rebuild
```

Standardpfad der Datenbank:

- `data/grundschul_woerterbuch.sqlite3`

Wenn Beziehungen auf noch nicht vorhandene Woerter verweisen, sammelt das Importskript diese Zielwoerter automatisch in:

- `data/missing_relation_words.txt`
- `data/missing_relation_report.json`
- `data/missing_relation_words_next.txt`

Dabei gilt:

- `missing_relation_words.txt`: alle fehlenden Zielwoerter
- `missing_relation_report.json`: strukturierter Bericht mit Haeufigkeiten, Beziehungstypen und Quellwoertern
- `missing_relation_words_next.txt`: priorisierte Liste fuer den naechsten Gemini-Lauf

Die priorisierte Liste bevorzugt aktuell:

- Woerter, die mehrfach als fehlendes Ziel auftauchen
- Woerter aus `word_family`
- starke Synonym-Kandidaten

## Neue Woerter mit Gemini erzeugen

Fuer groessere Wortlisten gibt es ein Helfer-Skript:

```bash
export GEMINI_API_KEY=dein_api_key
python3 scripts/generate_words_with_gemini.py woerterliste.txt --skip-existing
```

Das Skript:

- liest eine Textdatei mit einem Wort pro Zeile
- ruft `gemini-2.5-flash` auf
- erzeugt pro Wort eine JSON-Datei im Importverzeichnis
- ueberspringt Woerter, fuer die im Importverzeichnis bereits eine JSON-Datei existiert
- importiert die erzeugten Datensaetze anschliessend in SQLite
- legt Uebersetzungen fuer `en`, `fr`, `tr` und `ar` an
- ordnet jedem Wort mindestens ein Rechtschreibphaenomen zu, bei Bedarf auch mehrere
- erzeugt bei Nomen die Deklinationen fuer Nominativ, Genitiv, Dativ und Akkusativ in Singular und Plural
- behaelt in sichtbaren deutschen Texten Umlaute und `ß` bei

Nuetzliche Optionen:

- `--dry-run`: nur JSON erzeugen, noch nicht in SQLite importieren
- `--model gemini-2.5-flash`: anderes Gemini-Modell waehlen
- `--skip-existing`: bestehende Woerter in der Datenbank ueberspringen
- `--overwrite-json`: vorhandene JSON-Dateien im Importverzeichnis bewusst neu erzeugen

Alternativ kannst du auch eine Vertex-AI-Service-Account-Datei verwenden, zum Beispiel `key.json` im Projektverzeichnis. Das Skript erkennt standardmaessig:

- `./key.json`
- `./key3.json`
- `./scripts/key.json`
- `./scripts/key3.json`

Dann sind kein `GEMINI_API_KEY`, aber diese Vertex-AI-Variablen noetig bzw. werden vom Skript gesetzt:

- `GOOGLE_APPLICATION_CREDENTIALS`
- `GOOGLE_CLOUD_PROJECT`
- `GOOGLE_CLOUD_LOCATION`
- `GOOGLE_GENAI_USE_VERTEXAI=True`

Expliziter Aufruf:

```bash
python3 scripts/generate_words_with_gemini.py woerterliste.txt --credentials-file key.json
```

Vorhandene JSON-Dateien kannst du mit einem zweiten Helfer-Skript auf die Wortart pruefen:

```bash
python3 scripts/check_word_types_with_gemini.py --credentials-file key.json
```

Optional kannst du erkannte Abweichungen direkt zurueckschreiben:

```bash
python3 scripts/check_word_types_with_gemini.py --credentials-file key.json --apply
```

## Schreibproben mit Gemini

Der neue Prototyp fuer Schreibproben ist unter `http://127.0.0.1:5005/writing-check` erreichbar.

Standardmaessig versucht die App jetzt fuer diesen Bereich direkt Gemini mit `key.json` zu verwenden:

- `HANDWRITING_MODE=gemini`
- `HANDWRITING_GEMINI_MODEL=gemini-2.5-flash`
- `GEMINI_CREDENTIALS_FILE=./key.json`

Wenn `key.json` vorhanden und gueltig ist, startet die App den Dienst automatisch im Gemini-Modus. Falls die Initialisierung fehlschlaegt, faellt der Bereich fuer die Schreibprobe sichtbar auf einen Mock-Modus zurueck.

Nuetzliche Umgebungsvariablen:

- `HANDWRITING_MODE=gemini` oder `mock`
- `HANDWRITING_GEMINI_MODEL=gemini-2.5-flash`
- `GEMINI_CREDENTIALS_FILE=./key.json`
- `GEMINI_LOCATION=global`

## App starten

```bash
flask --app app run --debug
```

Danach ist die Anwendung lokal unter `http://127.0.0.1:5005/` erreichbar.

Hinweis:
Der Port `5005` wird ueber [`.flaskenv`](/home/emrichschule/GSWB/.flaskenv) gesetzt. Dafuer muss `python-dotenv` installiert sein, was jetzt in [requirements.txt](/home/emrichschule/GSWB/requirements.txt) enthalten ist.

## Spracheingabe mit whisper.cpp

Standardmaessig ist der Prototyp jetzt auf einen `whisper.cpp`-Dienst unter `http://192.168.178.86:8080/inference` eingestellt.

Konfigurierbare Umgebungsvariablen:

- `SPEECH_MODE=whisper_cpp` oder `mock`
- `WHISPER_CPP_URL=http://192.168.178.86:8080/inference`
- `WHISPER_CPP_TIMEOUT=20`
- `WHISPER_CPP_LANGUAGE=de`

Der Browser nimmt kurz Audio auf und sendet die Datei an `/api/speech-search`. Das Backend leitet sie an `whisper.cpp` weiter und schickt den erkannten Text dann durch dieselbe Such- und Normalisierungslogik wie bei der Texteingabe.

Fuer deutsche Spracheingabe sendet der Prototyp standardmaessig `language=de` an `whisper.cpp`.

## Mock-Modus

Standardmaessig laeuft die Spracheingabe im Mock-Modus:

- `SPEECH_MODE=mock`
- Rueckgabe erfolgt ueber `SPEECH_MOCK_RESULT`, standardmaessig `Hund`

Beispiel:

```bash
export SPEECH_MODE=mock
export SPEECH_MOCK_RESULT=schnell
flask --app app run --debug
```

Im Mock-Modus wird das konfigurierte Wort zurueckgegeben und dann durch dieselbe Suchlogik verarbeitet wie Texteingaben.

## Vorbereitung fuer whisper.cpp

Die Architektur ist ueber `SpeechRecognitionService` gekapselt. Falls dein `whisper.cpp`-Server eine leicht abweichende Antwortstruktur liefert, muss in der Regel nur [grundschul_woerterbuch/services/speech_service.py](/home/emrichschule/GSWB/grundschul_woerterbuch/services/speech_service.py) angepasst werden.

## Medien-Dateien

Die Wortseiten erwarten diese Pfade:

- Bilder: `static/images/WORT.webp`
- Audio: `static/audio/WORT.mp3`

Wenn Dateien fehlen, zeigt die App Platzhalter oder einen Hinweis an und bleibt stabil.

## Annahmen im Prototyp

- JSON-Dateien enthalten deutsche Feldnamen wie `wortart` oder `begriffserklaerung`.
- Umlaute werden fuer die Suchnormalisierung auf `ae`, `oe`, `ue` und `ss` abgebildet.
- Fuer den Prototypen sind nur die Wortarten `Nomen`, `Verb` und `Adjektiv` vorgesehen.
