import argparse
import json
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.generate_words_with_gemini import configure_auth, classify_part_of_speech

try:
    from google import genai
    from google.genai.types import HttpOptions
except ImportError:  # pragma: no cover
    genai = None
    HttpOptions = None


def parse_args():
    parser = argparse.ArgumentParser(
        description="Prueft die Wortart vorhandener JSON-Dateien mit Gemini und schreibt einen Bericht."
    )
    parser.add_argument(
        "--import-dir",
        default=str(ROOT_DIR / "data" / "import_words"),
        help="Verzeichnis mit JSON-Dateien",
    )
    parser.add_argument(
        "--model",
        default="gemini-2.5-flash",
        help="Gemini-Modellname",
    )
    parser.add_argument(
        "--credentials-file",
        default=None,
        help="Pfad zu einer Service-Account-JSON-Datei fuer Vertex AI, zum Beispiel key3.json",
    )
    parser.add_argument(
        "--location",
        default="global",
        help="Vertex-AI-Standort, standardmaessig global",
    )
    parser.add_argument(
        "--report-file",
        default=str(ROOT_DIR / "data" / "word_type_report.json"),
        help="Datei fuer den Pruefbericht",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Schreibt erkannte Wortarten direkt in die JSON-Dateien zurueck.",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.2,
        help="Kurze Pause zwischen den Anfragen, um Rate-Limits abzufedern.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=5,
        help="Wie oft bei 429/Rate-Limit erneut versucht werden soll.",
    )
    return parser.parse_args()


def write_report(report_file, report):
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def classify_with_retry(client, model, lemma, max_retries):
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            return classify_part_of_speech(client, model, lemma)
        except Exception as exc:  # pragma: no cover - haengt von externer API ab.
            last_error = exc
            error_text = str(exc)
            if "429" not in error_text and "RESOURCE_EXHAUSTED" not in error_text:
                raise
            wait_seconds = min(30, 2 ** (attempt - 1))
            print(
                f"Rate-Limit bei {lemma}, neuer Versuch in {wait_seconds} Sekunden "
                f"({attempt}/{max_retries})...",
                file=sys.stderr,
            )
            time.sleep(wait_seconds)
    raise last_error


def main():
    args = parse_args()
    if genai is None:
        print(
            "Das Paket 'google-genai' fehlt. Bitte zuerst 'pip install -r requirements.txt' ausfuehren.",
            file=sys.stderr,
        )
        return 1

    try:
        auth_info = configure_auth(args.credentials_file, args.location)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if auth_info["mode"] == "api_key":
        client = genai.Client()
        print("Authentifizierung: GEMINI_API_KEY")
    else:
        client = genai.Client(http_options=HttpOptions(api_version="v1"))
        print(
            "Authentifizierung: Vertex AI ueber Service Account "
            f"({auth_info['project_id']}, {auth_info['location']})"
        )

    import_dir = Path(args.import_dir)
    report_file = Path(args.report_file)
    report = []
    mismatches = 0
    errors = 0

    for json_file in sorted(import_dir.glob("*.json")):
        payload = json.loads(json_file.read_text(encoding="utf-8"))
        lemma = payload.get("lemma", json_file.stem)
        current_pos = payload.get("wortart", "")
        try:
            detected_pos, reasoning = classify_with_retry(client, args.model, lemma, args.max_retries)
        except Exception as exc:  # pragma: no cover - haengt von externer API ab.
            errors += 1
            entry = {
                "file": str(json_file),
                "lemma": lemma,
                "current_wortart": current_pos,
                "error": str(exc),
                "matches": False,
            }
            report.append(entry)
            write_report(report_file, report)
            print(f"Fehler bei {lemma}: {exc}", file=sys.stderr)
            continue

        entry = {
            "file": str(json_file),
            "lemma": lemma,
            "current_wortart": current_pos,
            "detected_wortart": detected_pos,
            "begruendung": reasoning,
            "matches": current_pos == detected_pos,
        }
        report.append(entry)
        write_report(report_file, report)

        if current_pos != detected_pos:
            mismatches += 1
            print(f"Abweichung bei {lemma}: {current_pos} -> {detected_pos}")
            if args.apply:
                payload["wortart"] = detected_pos
                payload["wortart_pruefung"] = {
                    "detected_wortart": detected_pos,
                    "begruendung": reasoning,
                    "current_wortart": current_pos,
                }
                json_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        if args.delay_seconds > 0:
            time.sleep(args.delay_seconds)

    print(f"Bericht gespeichert: {report_file}")
    if errors:
        print(f"Fehler bei {errors} Dateien.")
    if mismatches:
        print(f"Gefundene Abweichungen: {mismatches}")
        return 1
    print("Keine Abweichungen gefunden.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
