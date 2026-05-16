import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from grundschul_woerterbuch.db import get_connection, init_db
from grundschul_woerterbuch.services.search_service import SearchService


VALID_POS = {
    "Nomen", "Verb", "Adjektiv", "Adverb", "Pronomen",
    "Präposition", "Konjunktion", "Interjektion", "Numerale",
    "Artikel", "Partikel",
}
VALID_RELATION_TYPES = {"word_family", "word_field", "synonym"}
VALID_SPELLING_CATEGORIES = {
    "Wort mit Kürzezeichen",
    "Verlängerungswort",
    "Ableitungswort",
    "Mitsprechwort",
    "Bausteinwort",
    "Merkwort mit Dehnungs-h",
    "Merkwort mit ß",
    "Merkwort mit ie",
    "Merkwort mit V",
    "Merkwort mit X",
    "Merkwort mit Qu",
    "Merkwort mit doppeltem Vokal",
}
REQUIRED_FIELDS = ["lemma", "wortart", "silben", "beispielsatz", "begriffserklaerung"]


def parse_args():
    parser = argparse.ArgumentParser(description="Importiert Beispielwoerter aus JSON-Dateien in SQLite.")
    parser.add_argument(
        "--database",
        default=str(ROOT_DIR / "data" / "grundschul_woerterbuch.sqlite3"),
        help="Pfad zur SQLite-Datenbank",
    )
    parser.add_argument(
        "--import-dir",
        default=str(ROOT_DIR / "data" / "import_words"),
        help="Verzeichnis mit JSON-Dateien",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Loescht bestehende Daten und importiert die Beispieldaten neu.",
    )
    parser.add_argument(
        "--missing-relations-file",
        default=str(ROOT_DIR / "data" / "missing_relation_words.txt"),
        help="Datei, in die fehlende Zielwoerter aus Beziehungen gesammelt geschrieben werden.",
    )
    parser.add_argument(
        "--missing-relations-report",
        default=str(ROOT_DIR / "data" / "missing_relation_report.json"),
        help="JSON-Bericht mit Haeufigkeiten, Quellwoertern und Beziehungstypen fehlender Zielwoerter.",
    )
    parser.add_argument(
        "--missing-relations-next-file",
        default=str(ROOT_DIR / "data" / "missing_relation_words_next.txt"),
        help="Priorisierte Wortliste fuer den naechsten Gemini-Lauf.",
    )
    return parser.parse_args()


def validate_payload(payload, filename):
    errors = []
    for field in REQUIRED_FIELDS:
        if not payload.get(field):
            errors.append(f"{filename}: Feld '{field}' fehlt oder ist leer.")

    if payload.get("wortart") not in VALID_POS:
        errors.append(f"{filename}: wortart muss eine der Werte {sorted(VALID_POS)} sein.")

    for translation in payload.get("uebersetzungen", []):
        if not translation.get("language_code") or not translation.get("translation"):
            errors.append(f"{filename}: Jede Uebersetzung braucht 'language_code' und 'translation'.")

    for relation in payload.get("beziehungen", []):
        relation_type = relation.get("relation_type")
        if relation_type not in VALID_RELATION_TYPES:
            errors.append(
                f"{filename}: relation_type '{relation_type}' ist ungueltig. Erlaubt: {sorted(VALID_RELATION_TYPES)}."
            )
        if not relation.get("target_lemma"):
            errors.append(f"{filename}: Beziehung ohne target_lemma gefunden.")

    for category in payload.get("rechtschreibkategorien", []):
        if category not in VALID_SPELLING_CATEGORIES:
            errors.append(
                f"{filename}: Rechtschreibkategorie '{category}' ist ungueltig. Erlaubt: {sorted(VALID_SPELLING_CATEGORIES)}."
            )
    for family_base in payload.get("wortfamilie_basen", []):
        if not str(family_base).strip():
            errors.append(f"{filename}: wortfamilie_basen darf keine leeren Eintraege enthalten.")
    if not payload.get("rechtschreibkategorien"):
        errors.append(f"{filename}: Mindestens ein Rechtschreibphaenomen muss gesetzt sein.")

    grammar = payload.get("grammatische_formen", {})
    pos = payload.get("wortart")
    if pos == "Nomen":
        if not grammar.get("artikel") or not grammar.get("singular") or not grammar.get("plural"):
            errors.append(f"{filename}: Nomen brauchen artikel, singular und plural.")
        deklination = grammar.get("deklination", {})
        if not has_complete_case_table(deklination):
            errors.append(
                f"{filename}: Nomen brauchen eine vollstaendige Deklination mit Nominativ, Genitiv, Dativ und Akkusativ in Singular und Plural."
            )
    elif pos == "Verb":
        if not grammar.get("infinitiv"):
            errors.append(f"{filename}: Verben brauchen einen infinitiv.")
        for tense in ["praesens", "perfekt", "praeteritum"]:
            if not has_complete_person_table(grammar.get(tense, {})):
                errors.append(
                    f"{filename}: Verben brauchen eine vollstaendige Tabelle fuer {tense} mit ich, du, er_sie_es, wir, ihr und sie."
                )
    elif pos == "Adjektiv":
        if not grammar.get("positiv") or not grammar.get("komparativ") or not grammar.get("superlativ"):
            errors.append(f"{filename}: Adjektive brauchen positiv, komparativ und superlativ.")

    return errors


def has_complete_case_table(deklination):
    if not isinstance(deklination, dict):
        return False
    required_cases = ["nominativ", "genitiv", "dativ", "akkusativ"]
    for number in ["singular", "plural"]:
        forms = deklination.get(number, {})
        if not isinstance(forms, dict):
            return False
        for case_name in required_cases:
            if not forms.get(case_name):
                return False
    return True


def has_complete_person_table(forms):
    if not isinstance(forms, dict):
        return False
    return all(forms.get(person) for person in ["ich", "du", "er_sie_es", "wir", "ihr", "sie"])


def clear_tables(connection):
    for table in [
        "relations",
        "translations",
        "spelling_categories",
        "word_family_bases",
        "misspellings",
        "noun_forms",
        "verb_forms",
        "adjective_forms",
        "words",
    ]:
        connection.execute(f"DELETE FROM {table}")


def insert_word(connection, payload):
    normalized_lemma = SearchService.normalize(payload["lemma"])
    existing = connection.execute(
        "SELECT id FROM words WHERE normalized_lemma = ?",
        (normalized_lemma,),
    ).fetchone()

    if existing:
        word_id = existing["id"]
        connection.execute(
            """
            UPDATE words
            SET lemma = ?, part_of_speech = ?, syllables = ?, example_sentence = ?,
                definition = ?, spelling_strategy = ?, image_filename = ?, audio_filename = ?
            WHERE id = ?
            """,
            (
                payload["lemma"],
                payload["wortart"],
                payload.get("silben"),
                payload.get("beispielsatz"),
                payload.get("begriffserklaerung"),
                payload.get("rechtschreibstrategie"),
                payload.get("bild_datei"),
                payload.get("audio_datei"),
                word_id,
            ),
        )
        for table in [
            "translations",
            "spelling_categories",
            "word_family_bases",
            "misspellings",
            "noun_forms",
            "verb_forms",
            "adjective_forms",
        ]:
            connection.execute(f"DELETE FROM {table} WHERE word_id = ?", (word_id,))
        connection.execute("DELETE FROM relations WHERE source_word_id = ? OR target_word_id = ?", (word_id, word_id))
    else:
        cursor = connection.execute(
            """
            INSERT INTO words (
                lemma, normalized_lemma, part_of_speech, syllables, example_sentence,
                definition, spelling_strategy, image_filename, audio_filename
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["lemma"],
                normalized_lemma,
                payload["wortart"],
                payload.get("silben"),
                payload.get("beispielsatz"),
                payload.get("begriffserklaerung"),
                payload.get("rechtschreibstrategie"),
                payload.get("bild_datei"),
                payload.get("audio_datei"),
            ),
        )
        word_id = cursor.lastrowid

    for translation in payload.get("uebersetzungen", []):
        connection.execute(
            """
            INSERT OR REPLACE INTO translations (word_id, language_code, translation)
            VALUES (?, ?, ?)
            """,
            (word_id, translation["language_code"], translation["translation"]),
        )

    for category in payload.get("rechtschreibkategorien", []):
        connection.execute(
            """
            INSERT OR IGNORE INTO spelling_categories (word_id, category)
            VALUES (?, ?)
            """,
            (word_id, category),
        )

    for family_base in payload.get("wortfamilie_basen", []):
        cleaned = str(family_base).strip()
        if not cleaned:
            continue
        connection.execute(
            """
            INSERT OR IGNORE INTO word_family_bases (word_id, family_base, normalized_family_base)
            VALUES (?, ?, ?)
            """,
            (word_id, cleaned, SearchService.normalize(cleaned)),
        )

    for misspelling in payload.get("fehlschreibungen", []):
        connection.execute(
            """
            INSERT OR IGNORE INTO misspellings (word_id, variant)
            VALUES (?, ?)
            """,
            (word_id, SearchService.normalize(misspelling)),
        )

    grammar = payload.get("grammatische_formen", {})
    if payload["wortart"] == "Nomen" and grammar:
        deklination = grammar.get("deklination", {})
        singular = deklination.get("singular", {})
        plural = deklination.get("plural", {})
        connection.execute(
            """
            INSERT OR REPLACE INTO noun_forms (
                word_id, article, singular_form, plural_form,
                nominativ_singular, genitiv_singular, dativ_singular, akkusativ_singular,
                nominativ_plural, genitiv_plural, dativ_plural, akkusativ_plural
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                word_id,
                grammar.get("artikel"),
                grammar.get("singular"),
                grammar.get("plural"),
                singular.get("nominativ"),
                singular.get("genitiv"),
                singular.get("dativ"),
                singular.get("akkusativ"),
                plural.get("nominativ"),
                plural.get("genitiv"),
                plural.get("dativ"),
                plural.get("akkusativ"),
            ),
        )
    elif payload["wortart"] == "Verb" and grammar:
        praesens = grammar.get("praesens", {})
        perfekt = grammar.get("perfekt", {})
        praeteritum = grammar.get("praeteritum", {})
        connection.execute(
            """
            INSERT OR REPLACE INTO verb_forms (
                word_id, infinitive, ich_form, du_form, er_sie_es_form, wir_form, ihr_form, sie_form,
                perfekt_ich, perfekt_du, perfekt_er_sie_es, perfekt_wir, perfekt_ihr, perfekt_sie,
                praeteritum_ich, praeteritum_du, praeteritum_er_sie_es, praeteritum_wir, praeteritum_ihr, praeteritum_sie
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                word_id,
                grammar.get("infinitiv"),
                praesens.get("ich", grammar.get("ich")),
                praesens.get("du", grammar.get("du")),
                praesens.get("er_sie_es", grammar.get("er_sie_es")),
                praesens.get("wir", grammar.get("wir")),
                praesens.get("ihr", grammar.get("ihr")),
                praesens.get("sie", grammar.get("sie")),
                perfekt.get("ich"),
                perfekt.get("du"),
                perfekt.get("er_sie_es"),
                perfekt.get("wir"),
                perfekt.get("ihr"),
                perfekt.get("sie"),
                praeteritum.get("ich"),
                praeteritum.get("du"),
                praeteritum.get("er_sie_es"),
                praeteritum.get("wir"),
                praeteritum.get("ihr"),
                praeteritum.get("sie"),
            ),
        )
    elif payload["wortart"] == "Adjektiv" and grammar:
        connection.execute(
            """
            INSERT OR REPLACE INTO adjective_forms (
                word_id, positive_form, comparative_form, superlative_form
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                word_id,
                grammar.get("positiv"),
                grammar.get("komparativ"),
                grammar.get("superlativ"),
            ),
        )

    return word_id


def insert_relations(connection, payloads_by_lemma):
    word_ids = {
        row["lemma"]: row["id"]
        for row in connection.execute("SELECT id, lemma FROM words").fetchall()
    }
    skipped_relations = []
    skipped_sources = []

    for payload in payloads_by_lemma.values():
        source_lemma = str(payload.get("lemma", "")).strip()
        source_id = word_ids.get(source_lemma)
        if not source_id:
            skipped_sources.append(source_lemma)
            continue
        for relation in payload.get("beziehungen", []):
            target_lemma = relation["target_lemma"]
            target_id = word_ids.get(target_lemma)
            if not target_id:
                skipped_relations.append((source_lemma, target_lemma, relation["relation_type"]))
                continue
            connection.execute(
                """
                INSERT OR IGNORE INTO relations (source_word_id, target_word_id, relation_type)
                VALUES (?, ?, ?)
                """,
                (source_id, target_id, relation["relation_type"]),
            )
    return skipped_relations, skipped_sources


def filter_truly_missing_relations(connection, skipped_relations):
    rows = connection.execute("SELECT normalized_lemma FROM words").fetchall()
    existing_normalized = {row["normalized_lemma"] for row in rows}
    return [
        (source_lemma, target_lemma, relation_type)
        for source_lemma, target_lemma, relation_type in skipped_relations
        if SearchService.normalize(target_lemma) not in existing_normalized
    ]


def write_missing_relation_words(output_path, skipped_relations):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    missing_words = sorted({target_lemma for _, target_lemma, _ in skipped_relations})
    output_path.write_text("\n".join(missing_words) + ("\n" if missing_words else ""), encoding="utf-8")
    return missing_words


def build_missing_relation_report(skipped_relations):
    by_target = defaultdict(lambda: {"count": 0, "relation_types": Counter(), "source_lemmas": set()})
    for source_lemma, target_lemma, relation_type in skipped_relations:
        item = by_target[target_lemma]
        item["count"] += 1
        item["relation_types"][relation_type] += 1
        item["source_lemmas"].add(source_lemma)

    report_items = []
    for target_lemma, item in by_target.items():
        relation_types = dict(item["relation_types"])
        relation_priority = relation_types.get("word_family", 0) * 4 + relation_types.get("synonym", 0) * 2 + relation_types.get("word_field", 0)
        score = item["count"] + relation_priority
        report_items.append(
            {
                "target_lemma": target_lemma,
                "count": item["count"],
                "relation_types": relation_types,
                "source_lemmas": sorted(item["source_lemmas"]),
                "score": score,
            }
        )

    report_items.sort(key=lambda item: (-item["score"], -item["count"], item["target_lemma"].lower()))
    return report_items


def write_missing_relation_report(report_path, report_items):
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report_items, ensure_ascii=False, indent=2), encoding="utf-8")


def write_next_missing_relation_words(output_path, report_items):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    selected = []
    for item in report_items:
        relation_types = item["relation_types"]
        if item["count"] >= 2:
            selected.append(item["target_lemma"])
            continue
        if relation_types.get("word_family", 0) >= 1:
            selected.append(item["target_lemma"])
            continue
        if relation_types.get("synonym", 0) >= 2:
            selected.append(item["target_lemma"])

    output_path.write_text("\n".join(selected) + ("\n" if selected else ""), encoding="utf-8")
    return selected


def main():
    args = parse_args()
    database_path = Path(args.database)
    import_dir = Path(args.import_dir)
    missing_relations_file = Path(args.missing_relations_file)
    missing_relations_report = Path(args.missing_relations_report)
    missing_relations_next_file = Path(args.missing_relations_next_file)

    init_db(str(database_path))

    if not import_dir.exists():
        print(f"Importverzeichnis nicht gefunden: {import_dir}", file=sys.stderr)
        return 1

    payloads = {}
    validation_errors = []
    skipped_files = []
    for json_file in sorted(import_dir.glob("*.json")):
        try:
            payload = json.loads(json_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            validation_errors.append(f"{json_file.name}: JSON ist ungueltig ({exc}).")
            continue

        if payload.get("wortart") not in VALID_POS:
            skipped_files.append((json_file.name, payload.get("wortart", "")))
            continue

        validation_errors.extend(validate_payload(payload, json_file.name))
        payloads[payload.get("lemma", json_file.stem)] = payload

    if validation_errors:
        print("Import abgebrochen. Bitte zuerst diese Probleme beheben:", file=sys.stderr)
        for error in validation_errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    with get_connection(str(database_path)) as connection:
        if args.rebuild:
            clear_tables(connection)

        for payload in payloads.values():
            insert_word(connection, payload)

        skipped_relations, skipped_sources = insert_relations(connection, payloads)
        connection.commit()
        truly_missing_relations = filter_truly_missing_relations(connection, skipped_relations)

    missing_words = write_missing_relation_words(missing_relations_file, truly_missing_relations)
    report_items = build_missing_relation_report(truly_missing_relations)
    write_missing_relation_report(missing_relations_report, report_items)
    next_words = write_next_missing_relation_words(missing_relations_next_file, report_items)
    print(f"Import erfolgreich: {len(payloads)} Woerter in {database_path}")
    for source_lemma in skipped_sources:
        print(
            f"Hinweis: Beziehungen fuer '{source_lemma}' wurden uebersprungen, weil das Quellwort nicht in der Datenbank gelandet ist.",
            file=sys.stderr,
        )
    for filename, part_of_speech in skipped_files:
        print(
            f"Hinweis: {filename} wurde beim Import uebersprungen, weil die Wortart '{part_of_speech}' aktuell nicht in die App importiert wird.",
            file=sys.stderr,
        )
    for source_lemma, target_lemma, relation_type in skipped_relations:
        print(
            f"Hinweis: Beziehung uebersprungen ({source_lemma} -> {target_lemma}, {relation_type}), "
            "weil das Zielwort nicht importiert wurde.",
            file=sys.stderr,
        )
    if missing_words:
        print(
            f"Fehlende Zielwoerter wurden in {missing_relations_file} gesammelt: {', '.join(missing_words)}",
            file=sys.stderr,
        )
        print(
            f"Strukturierter Bericht: {missing_relations_report}",
            file=sys.stderr,
        )
        print(
            f"Priorisierte Liste fuer den naechsten Gemini-Lauf ({len(next_words)} Woerter): {missing_relations_next_file}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
