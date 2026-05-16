import argparse
import json
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.generate_words_with_gemini import HttpOptions, configure_auth, genai, request_json_with_schema


WORD_FAMILY_BASES_SCHEMA = {
    "type": "object",
    "properties": {
        "wortfamilie_basen": {
            "type": "array",
            "items": {"type": "string"},
        },
        "begruendung": {"type": "string"},
    },
    "required": ["wortfamilie_basen", "begruendung"],
    "additionalProperties": False,
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Ergaenzt vorhandene JSON-Dateien um eine oder mehrere Wortfamilien-Basen."
    )
    parser.add_argument(
        "--import-dir",
        default=str(ROOT_DIR / "data" / "import_words"),
        help="Verzeichnis mit JSON-Dateien.",
    )
    parser.add_argument(
        "--credentials-file",
        default=None,
        help="Optionale Service-Account-Datei fuer Vertex AI.",
    )
    parser.add_argument(
        "--location",
        default="global",
        help="Vertex-AI-Standort.",
    )
    parser.add_argument(
        "--model",
        default="gemini-2.5-flash",
        help="Gemini-Modell fuer die Wortfamilien-Bestimmung.",
    )
    parser.add_argument(
        "--overwrite-existing",
        action="store_true",
        help="Vorhandene wortfamilie_basen ueberschreiben.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximale Anzahl Dateien; 0 bedeutet ohne Limit.",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.0,
        help="Kurze Pause zwischen Anfragen, um Rate Limits zu schonen.",
    )
    return parser.parse_args()


def build_client(auth_info):
    if auth_info["mode"] == "api_key":
        print("Authentifizierung: GEMINI_API_KEY")
        return genai.Client()

    print(
        "Authentifizierung: Vertex AI ueber Service Account "
        f"({auth_info['project_id']}, {auth_info['location']})"
    )
    return genai.Client(http_options=HttpOptions(api_version="v1"))


def build_prompt(payload):
    lemma = payload.get("lemma", "").strip()
    part_of_speech = payload.get("wortart", "").strip()
    relations = payload.get("beziehungen", [])
    relation_lines = [
        f"- {relation.get('relation_type')}: {relation.get('target_lemma')}"
        for relation in relations
        if relation.get("relation_type") == "word_family" and relation.get("target_lemma")
    ]
    relation_block = "\n".join(relation_lines) if relation_lines else "- keine vorhandenen word_family-Beziehungen"

    return f"""
Bestimme fuer das deutsche Wort '{lemma}' eine oder mehrere passende Wortfamilien-Basen.

Wortart: {part_of_speech}
Vorhandene direkte word_family-Beziehungen:
{relation_block}

Definition fuer Wortfamilie:
Eine Wortfamilie ist eine Gruppe von Wörtern, die vom selben Wortstamm abstammen und in ihrer Bedeutung verwandt sind.
Nutze als Basis moeglichst das gemeinsame Grundwort oder die gemeinsame Stammform.

Wichtige Regeln:
- Gib nur Basen zurueck, die fachlich wirklich passen.
- Ein Wort kann mehrere Basen haben, zum Beispiel Haarbürste -> Haar und Bürste.
- Wenn nur eine Basis passt, gib genau eine zurueck.
- Vermeide zu konkrete Ableitungen als Basis, wenn eine bessere gemeinsame Stammform moeglich ist.
- Beispiel: laufen, Läufer, Laufschuh -> Basis Lauf.
- Nutze echte deutsche Schreibweise mit Umlauten und ß.
- Gib keine leeren oder doppelten Eintraege zurueck.
- Gib nur JSON zurueck.
""".strip()


def clean_family_bases(values):
    cleaned = []
    seen = set()
    for value in values:
        text = " ".join(str(value).strip().split())
        key = text.casefold()
        if text and key not in seen:
            cleaned.append(text)
            seen.add(key)
    return cleaned


def main():
    if genai is None or HttpOptions is None:
        print("Das Paket 'google-genai' ist nicht installiert.", file=sys.stderr)
        return 1

    args = parse_args()
    import_dir = Path(args.import_dir)
    if not import_dir.exists():
        print(f"Importverzeichnis nicht gefunden: {import_dir}", file=sys.stderr)
        return 1

    auth_info = configure_auth(args.credentials_file, args.location)
    client = build_client(auth_info)

    processed = 0
    updated = 0
    skipped = 0
    failed = []

    for json_file in sorted(import_dir.glob("*.json")):
        if args.limit and processed >= args.limit:
            break

        payload = json.loads(json_file.read_text(encoding="utf-8"))
        processed += 1

        if payload.get("wortart") not in {"Nomen", "Verb", "Adjektiv"}:
            skipped += 1
            continue

        if payload.get("wortfamilie_basen") and not args.overwrite_existing:
            skipped += 1
            continue

        lemma = payload.get("lemma", json_file.stem)
        print(f"Bestimme Wortfamilien-Basen: {lemma}")

        try:
            result = request_json_with_schema(
                client,
                args.model,
                build_prompt(payload),
                WORD_FAMILY_BASES_SCHEMA,
                lemma,
                "word_family_bases",
            )
            payload["wortfamilie_basen"] = clean_family_bases(result.get("wortfamilie_basen", []))
            payload["wortfamilie_basen_pruefung"] = {
                "modell": args.model,
                "begruendung": result.get("begruendung", "").strip(),
            }
            json_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            updated += 1
        except Exception as exc:  # pragma: no cover - Laufzeit-/API-Fehler
            failed.append((lemma, str(exc)))
            print(f"Fehler bei {lemma}: {exc}", file=sys.stderr)

        if args.delay_seconds:
            time.sleep(args.delay_seconds)

    print(f"Verarbeitet: {processed}")
    print(f"Aktualisiert: {updated}")
    print(f"Uebersprungen: {skipped}")
    if failed:
        print("Fehlgeschlagen:", file=sys.stderr)
        for lemma, error in failed:
            print(f"- {lemma}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
