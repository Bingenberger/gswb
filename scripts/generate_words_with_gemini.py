import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from grundschul_woerterbuch.db import get_connection, init_db
from scripts.import_words import insert_relations, insert_word, validate_payload

try:
    from google import genai
    from google.genai.types import HttpOptions
except ImportError:  # pragma: no cover - haengt von optionalem Paket ab.
    genai = None
    HttpOptions = None


SUPPORTED_WORD_TYPES = {"Nomen", "Verb", "Adjektiv"}


SCHEMA = {
    "type": "object",
    "properties": {
        "lemma": {"type": "string", "description": "Das Grundwort."},
        "wortart": {
            "type": "string",
            "enum": ["Nomen", "Verb", "Adjektiv"],
            "description": "Wortart des Lemmas.",
        },
        "silben": {"type": "string", "description": "Silbentrennung mit Bindestrichen."},
        "beispielsatz": {"type": "string", "description": "Kurzer, kindgerechter Beispielsatz auf Deutsch."},
        "begriffserklaerung": {"type": "string", "description": "Kurze, einfache Definition auf Deutsch."},
        "rechtschreibstrategie": {"type": "string", "description": "Einfache Rechtschreibhilfe fuer Kinder."},
        "rechtschreibkategorien": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
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
                ],
            },
            "description": "Eine oder mehrere passende Rechtschreibphaenomene. Mindestens eines ist Pflicht.",
        },
        "wortfamilie_basen": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Eine oder mehrere gemeinsame Basen der Wortfamilie, zum Beispiel ['Lauf'] oder ['Haar', 'Bürste'].",
        },
        "bild_datei": {"type": "string", "description": "Dateiname fuer das Bild, zum Beispiel Hund.webp."},
        "audio_datei": {"type": "string", "description": "Dateiname fuer das Audio, zum Beispiel Hund.mp3."},
        "uebersetzungen": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "language_code": {"type": "string"},
                    "translation": {"type": "string"},
                },
                "required": ["language_code", "translation"],
                "additionalProperties": False,
            },
            "description": "Kurze Uebersetzungen fuer en, fr, tr und ar.",
        },
        "beziehungen": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "relation_type": {
                        "type": "string",
                        "enum": ["word_family", "word_field", "synonym"],
                    },
                    "target_lemma": {"type": "string"},
                },
                "required": ["relation_type", "target_lemma"],
                "additionalProperties": False,
            },
            "description": "Nur Beziehungen auf bekannte Woerter aus der erlaubten Zielliste.",
        },
        "grammatische_formen": {
            "type": "object",
            "description": "Je nach Wortart passende Flexionsformen. Andere Felder leer lassen oder weglassen.",
            "properties": {
                "artikel": {"type": "string"},
                "singular": {"type": "string"},
                "plural": {"type": "string"},
                "deklination": {
                    "type": "object",
                    "properties": {
                        "singular": {
                            "type": "object",
                            "properties": {
                                "nominativ": {"type": "string"},
                                "genitiv": {"type": "string"},
                                "dativ": {"type": "string"},
                                "akkusativ": {"type": "string"},
                            },
                            "additionalProperties": False,
                        },
                        "plural": {
                            "type": "object",
                            "properties": {
                                "nominativ": {"type": "string"},
                                "genitiv": {"type": "string"},
                                "dativ": {"type": "string"},
                                "akkusativ": {"type": "string"},
                            },
                            "additionalProperties": False,
                        },
                    },
                    "additionalProperties": False,
                },
                "infinitiv": {"type": "string"},
                "praesens": {
                    "type": "object",
                    "properties": {
                        "ich": {"type": "string"},
                        "du": {"type": "string"},
                        "er_sie_es": {"type": "string"},
                        "wir": {"type": "string"},
                        "ihr": {"type": "string"},
                        "sie": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "perfekt": {
                    "type": "object",
                    "properties": {
                        "ich": {"type": "string"},
                        "du": {"type": "string"},
                        "er_sie_es": {"type": "string"},
                        "wir": {"type": "string"},
                        "ihr": {"type": "string"},
                        "sie": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "praeteritum": {
                    "type": "object",
                    "properties": {
                        "ich": {"type": "string"},
                        "du": {"type": "string"},
                        "er_sie_es": {"type": "string"},
                        "wir": {"type": "string"},
                        "ihr": {"type": "string"},
                        "sie": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "positiv": {"type": "string"},
                "komparativ": {"type": "string"},
                "superlativ": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "fehlschreibungen": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Einige typische Kinderfehlschreibungen oder lautnahe Varianten.",
        },
    },
    "required": [
        "lemma",
        "wortart",
        "silben",
        "beispielsatz",
        "begriffserklaerung",
        "rechtschreibstrategie",
        "rechtschreibkategorien",
        "wortfamilie_basen",
        "bild_datei",
        "audio_datei",
        "uebersetzungen",
        "beziehungen",
        "grammatische_formen",
        "fehlschreibungen",
    ],
    "additionalProperties": False,
}

POS_CLASSIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "wortart": {
            "type": "string",
            "enum": [
                "Nomen",
                "Verb",
                "Adjektiv",
                "Adverb",
                "Pronomen",
                "Präposition",
                "Konjunktion",
                "Interjektion",
                "Numerale",
                "Artikel",
                "Partikel",
            ],
        },
        "begruendung": {"type": "string"},
    },
    "required": ["wortart", "begruendung"],
    "additionalProperties": False,
}

NOUN_GRAMMAR_SCHEMA = {
    "type": "object",
    "properties": {
        "artikel": {"type": "string"},
        "singular": {"type": "string"},
        "plural": {"type": "string"},
        "deklination": {
            "type": "object",
            "properties": {
                "singular": {
                    "type": "object",
                    "properties": {
                        "nominativ": {"type": "string"},
                        "genitiv": {"type": "string"},
                        "dativ": {"type": "string"},
                        "akkusativ": {"type": "string"},
                    },
                    "required": ["nominativ", "genitiv", "dativ", "akkusativ"],
                    "additionalProperties": False,
                },
                "plural": {
                    "type": "object",
                    "properties": {
                        "nominativ": {"type": "string"},
                        "genitiv": {"type": "string"},
                        "dativ": {"type": "string"},
                        "akkusativ": {"type": "string"},
                    },
                    "required": ["nominativ", "genitiv", "dativ", "akkusativ"],
                    "additionalProperties": False,
                },
            },
            "required": ["singular", "plural"],
            "additionalProperties": False,
        },
    },
    "required": ["artikel", "singular", "plural", "deklination"],
    "additionalProperties": False,
}

VERB_GRAMMAR_SCHEMA = {
    "type": "object",
    "properties": {
        "infinitiv": {"type": "string"},
        "praesens": {
            "type": "object",
            "properties": {
                "ich": {"type": "string"},
                "du": {"type": "string"},
                "er_sie_es": {"type": "string"},
                "wir": {"type": "string"},
                "ihr": {"type": "string"},
                "sie": {"type": "string"},
            },
            "required": ["ich", "du", "er_sie_es", "wir", "ihr", "sie"],
            "additionalProperties": False,
        },
        "perfekt": {
            "type": "object",
            "properties": {
                "ich": {"type": "string"},
                "du": {"type": "string"},
                "er_sie_es": {"type": "string"},
                "wir": {"type": "string"},
                "ihr": {"type": "string"},
                "sie": {"type": "string"},
            },
            "required": ["ich", "du", "er_sie_es", "wir", "ihr", "sie"],
            "additionalProperties": False,
        },
        "praeteritum": {
            "type": "object",
            "properties": {
                "ich": {"type": "string"},
                "du": {"type": "string"},
                "er_sie_es": {"type": "string"},
                "wir": {"type": "string"},
                "ihr": {"type": "string"},
                "sie": {"type": "string"},
            },
            "required": ["ich", "du", "er_sie_es", "wir", "ihr", "sie"],
            "additionalProperties": False,
        },
    },
    "required": ["infinitiv", "praesens", "perfekt", "praeteritum"],
    "additionalProperties": False,
}

ADJECTIVE_GRAMMAR_SCHEMA = {
    "type": "object",
    "properties": {
        "positiv": {"type": "string"},
        "komparativ": {"type": "string"},
        "superlativ": {"type": "string"},
    },
    "required": ["positiv", "komparativ", "superlativ"],
    "additionalProperties": False,
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Erzeugt Woerterbuchdaten aus einer Wortliste mit Gemini 2.5 Flash und importiert sie in SQLite."
    )
    parser.add_argument("word_list", help="Textdatei mit einem Wort pro Zeile")
    parser.add_argument(
        "--database",
        default=str(ROOT_DIR / "data" / "grundschul_woerterbuch.sqlite3"),
        help="Pfad zur SQLite-Datenbank",
    )
    parser.add_argument(
        "--import-dir",
        default=str(ROOT_DIR / "data" / "import_words"),
        help="Verzeichnis fuer erzeugte JSON-Dateien",
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
        "--skip-existing",
        action="store_true",
        help="Ueberspringt Woerter, die bereits in der Datenbank vorhanden sind.",
    )
    parser.add_argument(
        "--overwrite-json",
        action="store_true",
        help="Erzeugt JSON-Dateien neu, auch wenn im Importverzeichnis schon eine Datei fuer das Wort existiert.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Erzeugt nur JSON-Dateien, importiert aber nicht in die Datenbank.",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="Wie oft Gemini pro Wort bei Validierungsfehlern erneut versuchen soll.",
    )
    return parser.parse_args()


def slugify(value):
    value = value.strip().lower()
    replacements = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}
    for old, new in replacements.items():
        value = value.replace(old, new)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "wort"


def load_words(word_list_path):
    words = []
    for line in word_list_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            words.append(strip_leading_article(stripped))
    return words


def strip_leading_article(text):
    words = text.strip().split()
    if len(words) < 2:
        return text.strip()

    first_word = words[0].lower()
    removable_articles = {
        "der",
        "die",
        "das",
        "dem",
        "den",
        "des",
        "ein",
        "eine",
        "einen",
        "einem",
        "einer",
        "eines",
    }
    if first_word in removable_articles:
        return " ".join(words[1:]).strip()
    return text.strip()


def configure_auth(credentials_file, location):
    if os.environ.get("GEMINI_API_KEY"):
        return {"mode": "api_key"}

    candidate_paths = []
    if credentials_file:
        candidate_paths.append(Path(credentials_file))
    else:
        candidate_paths.extend([ROOT_DIR / "key.json", ROOT_DIR / "scripts" / "key.json"])

    credentials_path = next((path for path in candidate_paths if path.exists()), None)
    if not credentials_path:
        raise RuntimeError(
            "Keine Authentifizierung gefunden. Setze GEMINI_API_KEY oder lege eine Service-Account-Datei wie key3.json ab."
        )

    payload = json.loads(credentials_path.read_text(encoding="utf-8"))
    if payload.get("type") != "service_account":
        raise RuntimeError(
            f"{credentials_path} ist keine unterstuetzte Service-Account-Datei."
        )

    project_id = payload.get("project_id")
    if not project_id:
        raise RuntimeError(f"In {credentials_path} fehlt project_id.")

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(credentials_path.resolve())
    os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
    os.environ["GOOGLE_CLOUD_LOCATION"] = location
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
    return {
        "mode": "vertex_ai_service_account",
        "credentials_file": str(credentials_path.resolve()),
        "project_id": project_id,
        "location": location,
    }


def get_existing_lemmas(database_path):
    init_db(str(database_path))
    with get_connection(str(database_path)) as connection:
        rows = connection.execute("SELECT lemma FROM words ORDER BY lemma").fetchall()
    return [row["lemma"] for row in rows]


def build_prompt(lemma, part_of_speech, allowed_targets, extra_instructions=""):
    prompt = f"""
Erzeuge genau einen JSON-Datensatz fuer ein kindgerechtes Grundschul-Woerterbuch.

Wort: {lemma}
Vorgegebene Wortart: {part_of_speech}

Wichtige Regeln:
- Schreibe alles auf Deutsch.
- Erhalte in allen fuer Kinder sichtbaren Texten die echten deutschen Zeichen: ä, ö, ü und ß.
- Schreibe also zum Beispiel 'Bäcker', 'größer', 'Fuß' und 'Straße' nicht als 'Baecker', 'groesser', 'Fuss' oder 'Strasse'.
- Formuliere kurz, freundlich und fuer Grundschulkinder verstaendlich.
- Verwende bei 'silben' Bindestriche zwischen den Silben.
- Nutze nur die Beziehungstypen word_family, word_field und synonym.
- Wenn du unsicher bist, gib bei 'beziehungen' lieber eine leere Liste zurueck.
- Verwende 'word_family' nur bei echter Wortverwandtschaft. Leite Wortfamilien aus demselben Wortstamm oder aus klaren Ableitungen ab.
- Bevorzuge bei 'word_family' die gemeinsame Stammform oder das Grundwort der Familie statt zufaellige Einzelableitungen. Beispiel: laufen, Läufer und Laufschuh gehoeren zur Wortfamilie 'Lauf'. Deshalb soll laufen eher auf Lauf zeigen als auf Läufer.
- Vermeide Kreiszuordnungen innerhalb der Wortfamilie. Wenn Lauf die passende Familienbasis ist, dann sollen laufen -> Lauf und Läufer -> Lauf moeglich sein, aber nicht laufen -> Läufer und Läufer -> laufen als Hauptzuordnung.
- Trage die Wortfamilien zusaetzlich in 'wortfamilie_basen' ein. Ein Wort kann eine oder mehrere Basen haben, zum Beispiel Haarbürste -> ['Haar', 'Bürste'].
- Verwende 'synonym' nur fuer sinnverwandte Woerter, die Kinder zwischen 7 und 12 Jahren verstehen koennen. Vermeide zu schwierige, zu abstrakte oder ungewoehnliche Synonyme.
- Verwende 'word_field' fuer thematisch zusammengehoerige Woerter, auch wenn sie nicht aus derselben Wortfamilie stammen.
- Finde fuer 'word_field' nach Moeglichkeit 0 bis 3 sinnvolle Zielwoerter.
- Verwechsle 'word_field' nicht mit 'word_family': thematische Naehe ist Wortfeld, gleiche Wortwurzel ist Wortfamilie.
- Es ist erlaubt, Beziehungsziele zu nennen, auch wenn sie noch nicht in der aktuellen Datenbank oder Wortliste vorkommen.
- Nutze fuer 'bild_datei' genau {lemma}.webp
- Nutze fuer 'audio_datei' genau {lemma}.mp3
- Liefere einige typische Kinderfehlschreibungen.
- Fuelle nur die grammatischen Formen passend zur Wortart sinnvoll.
- Setze im JSON bei 'wortart' genau den vorgegebenen Wert {part_of_speech}.
- Bei Nomen muss 'grammatische_formen' zusaetzlich eine 'deklination' mit den vier Faellen Nominativ, Genitiv, Dativ und Akkusativ in Singular und Plural enthalten.
- Bei Verben muss 'grammatische_formen' die Tabellen 'praesens', 'perfekt' und 'praeteritum' mit den Formen fuer ich, du, er_sie_es, wir, ihr und sie enthalten.
- Ordne das Wort in eine oder mehrere Rechtschreibkategorien ein. Erlaubt sind nur:
  - Wort mit Kürzezeichen
  - Verlängerungswort
  - Ableitungswort
  - Mitsprechwort
  - Bausteinwort
  - Merkwort mit Dehnungs-h
  - Merkwort mit ß
  - Merkwort mit ie
  - Merkwort mit V
  - Merkwort mit X
  - Merkwort mit Qu
  - Merkwort mit doppeltem Vokal
- Nutze 'Wort mit Kürzezeichen' bei doppeltem Konsonanten, ck oder tz mit kurzem Vokal davor.
- Nutze 'Verlängerungswort', wenn die Schreibung durch Verlängern deutlich wird, zum Beispiel Hund -> Hunde.
- Achte dabei besonders auf auslautendes d/t, b/p und g/k. Wenn ein Wort am Ende mit d, b oder g geschrieben wird und die Verlängerung diese Schreibung sichtbar macht, ist es ein Verlängerungswort und kein Mitsprechwort.
- Nutze 'Ableitungswort', wenn ein verwandtes Wort die Schreibung erklaert, zum Beispiel Bäcker -> backen.
- Nutze 'Mitsprechwort' nur dann, wenn kein anderes Rechtschreibphaenomen passt und alle Phoneme des Wortes mit dem Basisgraphem verschriftet werden.
- Nutze 'Bausteinwort' bei Zusammensetzungen oder erkennbaren Wortbausteinen.
- Nutze 'Merkwort mit Dehnungs-h' bei Vokalverlaengerung mit h.
- Nutze 'Merkwort mit ß' bei Wörtern mit ß.
- Nutze 'Merkwort mit ie' bei Wörtern mit ie.
- Nutze 'Merkwort mit V' bei Wörtern mit V.
- Nutze 'Merkwort mit X' bei Wörtern mit X.
- Nutze 'Merkwort mit Qu' bei Wörtern mit Qu.
- Nutze 'Merkwort mit doppeltem Vokal' bei doppeltem Vokal.
- Jedes Wort muss mindestens ein Rechtschreibphaenomen bekommen, darf aber mehrere haben.

Uebersetzungen muessen genau fuer diese Sprachen enthalten sein:
- en
- fr
- tr
- ar
""".strip()
    if extra_instructions:
        prompt = f"{prompt}\n\nKorrigiere bei diesem Versuch besonders diese Punkte:\n{extra_instructions.strip()}"
    return prompt


def sanitize_payload(payload, requested_lemma, allowed_targets):
    payload["lemma"] = requested_lemma
    payload["bild_datei"] = f"{requested_lemma}.webp"
    payload["audio_datei"] = f"{requested_lemma}.mp3"

    filtered_relations = []
    relation_counts = {"word_family": 0, "word_field": 0, "synonym": 0}
    for relation in payload.get("beziehungen", []):
        relation_type = relation.get("relation_type")
        target_lemma = str(relation.get("target_lemma", "")).strip()
        if relation_type in {"word_family", "word_field", "synonym"} and target_lemma and target_lemma != requested_lemma:
            if relation_type == "word_field" and relation_counts["word_field"] >= 3:
                continue
            filtered_relations.append(
                {"relation_type": relation_type, "target_lemma": target_lemma}
            )
            relation_counts[relation_type] += 1
    payload["beziehungen"] = filtered_relations

    family_bases = []
    seen_family_bases = set()
    for family_base in payload.get("wortfamilie_basen", []):
        cleaned = str(family_base).strip()
        normalized = re.sub(r"\s+", " ", cleaned)
        if normalized and normalized.casefold() not in seen_family_bases:
            family_bases.append(normalized)
            seen_family_bases.add(normalized.casefold())
    payload["wortfamilie_basen"] = family_bases

    categories = []
    seen_categories = set()
    for category in payload.get("rechtschreibkategorien", []):
        cleaned = str(category).strip()
        if cleaned and cleaned not in seen_categories:
            categories.append(cleaned)
            seen_categories.add(cleaned)
    if len(categories) > 1 and "Mitsprechwort" in categories:
        categories = [category for category in categories if category != "Mitsprechwort"]
    if not categories:
        categories = ["Mitsprechwort"]
    payload["rechtschreibkategorien"] = categories

    for key in ["silben", "beispielsatz", "begriffserklaerung", "rechtschreibstrategie"]:
        if key in payload and isinstance(payload[key], str):
            payload[key] = payload[key].strip()

    grammar = strip_nested_strings(payload.get("grammatische_formen", {}))
    payload["grammatische_formen"] = sanitize_grammar_for_part_of_speech(
        grammar,
        payload.get("wortart"),
        requested_lemma,
    )
    payload["rechtschreibkategorien"] = apply_spelling_heuristics(
        payload["lemma"],
        payload.get("wortart"),
        payload["grammatische_formen"],
        payload["rechtschreibkategorien"],
    )

    translations = []
    seen_languages = set()
    for item in payload.get("uebersetzungen", []):
        language_code = str(item.get("language_code", "")).strip().lower()
        translation = str(item.get("translation", "")).strip()
        if language_code and translation and language_code not in seen_languages:
            translations.append({"language_code": language_code, "translation": translation})
            seen_languages.add(language_code)
    payload["uebersetzungen"] = translations

    misspellings = []
    seen_misspellings = set()
    for item in payload.get("fehlschreibungen", []):
        normalized = str(item).strip()
        if normalized and normalized.lower() not in seen_misspellings:
            misspellings.append(normalized)
            seen_misspellings.add(normalized.lower())
    payload["fehlschreibungen"] = misspellings
    return payload


def strip_nested_strings(value):
    if isinstance(value, dict):
        return {key: strip_nested_strings(item) for key, item in value.items()}
    if isinstance(value, list):
        return [strip_nested_strings(item) for item in value]
    if isinstance(value, str):
        return value.strip()
    return value


def sanitize_grammar_for_part_of_speech(grammar, part_of_speech, requested_lemma):
    if not isinstance(grammar, dict):
        grammar = {}

    if part_of_speech == "Nomen":
        deklination = grammar.get("deklination", {})
        singular_forms = deklination.get("singular", {}) if isinstance(deklination, dict) else {}
        plural_forms = deklination.get("plural", {}) if isinstance(deklination, dict) else {}

        article = grammar.get("artikel", "") or extract_article_from_phrase(singular_forms.get("nominativ", ""))
        singular = grammar.get("singular", "") or extract_noun_from_phrase(singular_forms.get("nominativ", "")) or requested_lemma
        plural = grammar.get("plural", "") or extract_noun_from_phrase(plural_forms.get("nominativ", ""))
        inferred_deklination = build_noun_declension(article, singular, plural)

        return {
            "artikel": article,
            "singular": singular,
            "plural": plural,
            "deklination": {
                "singular": {
                    "nominativ": singular_forms.get("nominativ", inferred_deklination["singular"]["nominativ"]),
                    "genitiv": singular_forms.get("genitiv", inferred_deklination["singular"]["genitiv"]),
                    "dativ": singular_forms.get("dativ", inferred_deklination["singular"]["dativ"]),
                    "akkusativ": singular_forms.get("akkusativ", inferred_deklination["singular"]["akkusativ"]),
                },
                "plural": {
                    "nominativ": plural_forms.get("nominativ", inferred_deklination["plural"]["nominativ"]),
                    "genitiv": plural_forms.get("genitiv", inferred_deklination["plural"]["genitiv"]),
                    "dativ": plural_forms.get("dativ", inferred_deklination["plural"]["dativ"]),
                    "akkusativ": plural_forms.get("akkusativ", inferred_deklination["plural"]["akkusativ"]),
                },
            },
        }

    if part_of_speech == "Verb":
        return {
            "infinitiv": grammar.get("infinitiv", requested_lemma),
            "praesens": pick_person_table(grammar.get("praesens", {})),
            "perfekt": pick_person_table(grammar.get("perfekt", {})),
            "praeteritum": pick_person_table(grammar.get("praeteritum", {})),
        }

    if part_of_speech == "Adjektiv":
        return {
            "positiv": grammar.get("positiv", requested_lemma),
            "komparativ": grammar.get("komparativ", ""),
            "superlativ": grammar.get("superlativ", ""),
        }

    return {}


def apply_spelling_heuristics(lemma, part_of_speech, grammar, categories):
    normalized_categories = list(categories)
    category_set = set(normalized_categories)
    lemma_lower = (lemma or "").strip().lower()

    if looks_like_verlaengerungswort(lemma_lower, part_of_speech, grammar):
        category_set.add("Verlängerungswort")

    if len(category_set) > 1 and "Mitsprechwort" in category_set:
        category_set.remove("Mitsprechwort")

    ordered_categories = [category for category in normalized_categories if category in category_set]
    for category in sorted(category_set):
        if category not in ordered_categories:
            ordered_categories.append(category)
    return ordered_categories


def looks_like_verlaengerungswort(lemma_lower, part_of_speech, grammar):
    if not lemma_lower.endswith(("d", "b", "g")):
        return False

    comparison_forms = []
    if part_of_speech == "Nomen":
        comparison_forms.extend(
            [
                grammar.get("plural", ""),
                grammar.get("deklination", {}).get("plural", {}).get("nominativ", ""),
                grammar.get("deklination", {}).get("singular", {}).get("genitiv", ""),
            ]
        )
    elif part_of_speech == "Adjektiv":
        comparison_forms.extend([grammar.get("komparativ", ""), grammar.get("superlativ", "")])
    elif part_of_speech == "Verb":
        comparison_forms.extend(
            [
                grammar.get("praesens", {}).get("ich", ""),
                grammar.get("praesens", {}).get("du", ""),
                grammar.get("praeteritum", {}).get("ich", ""),
            ]
        )

    if any(form for form in comparison_forms):
        return True
    return False


def pick_person_table(source):
    if not isinstance(source, dict):
        source = {}
    return {
        "ich": source.get("ich", ""),
        "du": source.get("du", ""),
        "er_sie_es": source.get("er_sie_es", ""),
        "wir": source.get("wir", ""),
        "ihr": source.get("ihr", ""),
        "sie": source.get("sie", ""),
    }


def extract_article_from_phrase(text):
    if not isinstance(text, str):
        return ""
    words = text.strip().split()
    if len(words) >= 2 and words[0].lower() in {"der", "die", "das", "ein", "eine"}:
        return words[0]
    return ""


def extract_noun_from_phrase(text):
    if not isinstance(text, str):
        return ""
    words = text.strip().split()
    if not words:
        return ""
    if len(words) >= 2 and words[0].lower() in {"der", "die", "das", "ein", "eine"}:
        return " ".join(words[1:]).strip()
    return text.strip()


def build_noun_declension(article, singular, plural):
    article_lower = (article or "").strip().lower()
    singular = (singular or "").strip()
    plural = (plural or "").strip()

    singular_articles = {
        "der": {"nominativ": "der", "genitiv": "des", "dativ": "dem", "akkusativ": "den"},
        "das": {"nominativ": "das", "genitiv": "des", "dativ": "dem", "akkusativ": "das"},
        "die": {"nominativ": "die", "genitiv": "der", "dativ": "der", "akkusativ": "die"},
    }
    chosen_articles = singular_articles.get(article_lower, singular_articles["das"])

    genitive_singular = build_genitive_singular(article_lower, singular)
    dative_plural = build_dative_plural(plural)

    return {
        "singular": {
            "nominativ": join_phrase(chosen_articles["nominativ"], singular),
            "genitiv": join_phrase(chosen_articles["genitiv"], genitive_singular),
            "dativ": join_phrase(chosen_articles["dativ"], singular),
            "akkusativ": join_phrase(chosen_articles["akkusativ"], singular),
        },
        "plural": {
            "nominativ": join_phrase("die", plural),
            "genitiv": join_phrase("der", plural),
            "dativ": join_phrase("den", dative_plural),
            "akkusativ": join_phrase("die", plural),
        },
    }


def build_genitive_singular(article, singular):
    singular = (singular or "").strip()
    if not singular:
        return ""
    if article == "die":
        return singular

    lower = singular.lower()
    if lower.endswith(("s", "ß", "x", "z", "tz", "tsch", "ce")):
        return f"{singular}es"
    if len(singular) <= 1:
        return singular
    if lower.endswith(("el", "en", "er")):
        return f"{singular}s"
    return f"{singular}es" if len(singular) <= 2 else f"{singular}s"


def build_dative_plural(plural):
    plural = (plural or "").strip()
    if not plural:
        return ""
    lower = plural.lower()
    if lower.endswith(("n", "s")):
        return plural
    return f"{plural}n"


def join_phrase(article, noun):
    article = (article or "").strip()
    noun = (noun or "").strip()
    if article and noun:
        return f"{article} {noun}"
    return article or noun


def request_payload(client, model, lemma, part_of_speech, allowed_targets, extra_instructions=""):
    response = client.models.generate_content(
        model=model,
        contents=build_prompt(lemma, part_of_speech, allowed_targets, extra_instructions=extra_instructions),
        config={
            "response_mime_type": "application/json",
            "response_json_schema": SCHEMA,
        },
    )
    return parse_model_json_response(response.text, lemma)


def request_json_with_schema(client, model, prompt, schema, lemma, label):
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_json_schema": schema,
        },
    )
    return parse_model_json_response(response.text, f"{lemma}/{label}")


def parse_model_json_response(raw_text, lemma):
    candidates = []
    if raw_text:
        candidates.append(raw_text.strip())

        fenced_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw_text, flags=re.DOTALL)
        if fenced_match:
            candidates.append(fenced_match.group(1).strip())

        first_brace = raw_text.find("{")
        last_brace = raw_text.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            candidates.append(raw_text[first_brace:last_brace + 1].strip())

    errors = []
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            errors.append(f"{exc.msg} bei Position {exc.pos}")

    preview = (raw_text or "").strip().replace("\n", "\\n")
    preview = preview[:500]
    raise ValueError(
        f"Gemini lieferte fuer '{lemma}' kein gueltiges JSON. "
        f"Antwortanfang: {preview}. Parse-Fehler: {' | '.join(errors) if errors else 'unbekannt'}"
    )


def write_payload(import_dir, payload):
    filename = import_dir / f"{slugify(payload['lemma'])}.json"
    filename.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return filename


def classify_part_of_speech(client, model, lemma):
    prompt = f"""
Bestimme die Wortart des deutschen Wortes '{lemma}'.

Erlaubte Antworten:
- Nomen
- Verb
- Adjektiv
- Adverb
- Pronomen
- Präposition
- Konjunktion
- Interjektion
- Numerale
- Artikel
- Partikel

Wichtige Regeln:
- Verwende 'Adjektiv' nur, wenn das Wort wirklich eine Eigenschaft bezeichnet und sinnvoll gesteigert werden kann.
- Verwende 'Verb' nur, wenn es ein echtes Verb im Infinitiv oder eine klar erkennbare Verbgrundform ist.
- Verwende 'Nomen' nur, wenn das Wort als Ding, Lebewesen, Begriff oder Name mit Artikel verstanden wird.
- Verwende die spezifischste passende Wortart.
- Typische Faelle:
  - Adverb fuer Woerter wie heute, dort, gerne, bald
  - Pronomen fuer Woerter wie ich, du, wir, mein, dieser
  - Präposition fuer Woerter wie auf, unter, neben, wegen
  - Konjunktion fuer Woerter wie und, oder, weil, dass
  - Interjektion fuer Woerter wie oh, aua, hurra
  - Numerale fuer Zahlwoerter wie eins, zwei, erster
  - Artikel fuer der, die, das, ein, eine
  - Partikel fuer Woerter wie ja, doch, mal, nicht im Partikelgebrauch
- Ordne ein Wort niemals aus Verlegenheit als Adjektiv ein.

Gib nur JSON zurueck.
""".strip()
    result = request_json_with_schema(client, model, prompt, POS_CLASSIFICATION_SCHEMA, lemma, "pos")
    return result["wortart"], result.get("begruendung", "")


class UnsupportedWordTypeError(ValueError):
    def __init__(self, lemma, part_of_speech, reasoning):
        self.lemma = lemma
        self.part_of_speech = part_of_speech
        self.reasoning = reasoning
        super().__init__(
            f"'{lemma}' wurde als '{part_of_speech}' eingestuft und daher nicht als Nomen, Verb oder Adjektiv erzeugt. "
            f"Begruendung: {reasoning}"
        )


def generate_validated_payload(client, model, lemma, allowed_targets, max_attempts):
    part_of_speech, reasoning = classify_part_of_speech(client, model, lemma)
    if part_of_speech not in SUPPORTED_WORD_TYPES:
        raise UnsupportedWordTypeError(lemma, part_of_speech, reasoning)

    extra_instructions = ""
    last_errors = []
    last_payload = None

    for attempt in range(1, max_attempts + 1):
        payload = request_payload(
            client,
            model,
            lemma,
            part_of_speech,
            allowed_targets,
            extra_instructions=extra_instructions,
        )
        last_payload = payload
        payload = sanitize_payload(payload, lemma, allowed_targets)
        payload["wortart"] = part_of_speech
        validation_errors = validate_payload(payload, f"{lemma}.json")
        if not validation_errors:
            return payload

        last_errors = validation_errors
        error_lines = "\n".join(f"- {error}" for error in validation_errors)
        extra_instructions = (
            f"Dies ist Versuch {attempt + 1} von {max_attempts}. "
            "Der letzte Datensatz war noch unvollstaendig oder falsch. "
            f"Bitte liefere jetzt ein vollstaendig gueltiges JSON und behebe besonders:\n{error_lines}"
        )

    section_payload = try_sectional_repair(
        client,
        model,
        lemma,
        allowed_targets,
        base_payload=last_payload or {},
        part_of_speech=part_of_speech,
    )
    if section_payload is not None:
        validation_errors = validate_payload(section_payload, f"{lemma}.json")
        if not validation_errors:
            return section_payload
        last_errors = validation_errors

    raise ValueError(
        f"Fuer '{lemma}' konnte nach {max_attempts} Versuchen kein gueltiger Datensatz erzeugt werden:\n"
        + "\n".join(last_errors)
    )


def try_sectional_repair(client, model, lemma, allowed_targets, base_payload, part_of_speech):
    payload = sanitize_payload(dict(base_payload), lemma, allowed_targets)
    payload["wortart"] = part_of_speech
    grammar = request_grammar_section(client, model, lemma, part_of_speech)
    payload["grammatische_formen"] = grammar
    return sanitize_payload(payload, lemma, allowed_targets)


def request_grammar_section(client, model, lemma, part_of_speech):
    if part_of_speech == "Nomen":
        prompt = f"""
Erzeuge nur den JSON-Wert fuer 'grammatische_formen' des Nomens '{lemma}'.
Liefere unbedingt:
- artikel
- singular
- plural
- deklination.singular mit nominativ, genitiv, dativ, akkusativ
- deklination.plural mit nominativ, genitiv, dativ, akkusativ
Nutze echte deutsche Umlaute und ß.
Gib nur JSON zurueck.
""".strip()
        return request_json_with_schema(client, model, prompt, NOUN_GRAMMAR_SCHEMA, lemma, "noun_grammar")

    if part_of_speech == "Verb":
        prompt = f"""
Erzeuge nur den JSON-Wert fuer 'grammatische_formen' des Verbs '{lemma}'.
Liefere unbedingt:
- infinitiv
- praesens mit ich, du, er_sie_es, wir, ihr, sie
- perfekt mit ich, du, er_sie_es, wir, ihr, sie
- praeteritum mit ich, du, er_sie_es, wir, ihr, sie
Nutze echte deutsche Umlaute und ß.
Gib nur JSON zurueck.
""".strip()
        return request_json_with_schema(client, model, prompt, VERB_GRAMMAR_SCHEMA, lemma, "verb_grammar")

    prompt = f"""
Erzeuge nur den JSON-Wert fuer 'grammatische_formen' des Adjektivs '{lemma}'.
Liefere unbedingt:
- positiv
- komparativ
- superlativ
Nutze echte deutsche Umlaute und ß.
Gib nur JSON zurueck.
""".strip()
    return request_json_with_schema(client, model, prompt, ADJECTIVE_GRAMMAR_SCHEMA, lemma, "adjective_grammar")


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

    word_list_path = Path(args.word_list)
    import_dir = Path(args.import_dir)
    database_path = Path(args.database)

    if not word_list_path.exists():
        print(f"Wortliste nicht gefunden: {word_list_path}", file=sys.stderr)
        return 1

    init_db(str(database_path))
    import_dir.mkdir(parents=True, exist_ok=True)
    words = load_words(word_list_path)
    existing_lemmas = set(get_existing_lemmas(database_path))
    if auth_info["mode"] == "api_key":
        client = genai.Client()
        print("Authentifizierung: GEMINI_API_KEY")
    else:
        client = genai.Client(http_options=HttpOptions(api_version="v1"))
        print(
            "Authentifizierung: Vertex AI ueber Service Account "
            f"({auth_info['project_id']}, {auth_info['location']})"
        )

    payloads = {}
    failures = []
    for lemma in words:
        json_file = import_dir / f"{slugify(lemma)}.json"
        if json_file.exists() and not args.overwrite_json:
            print(f"Ueberspringe vorhandene JSON-Datei: {json_file}")
            continue

        if args.skip_existing and lemma in existing_lemmas:
            print(f"Ueberspringe bestehendes Wort: {lemma}")
            continue

        allowed_targets = set(existing_lemmas).union(words)
        allowed_targets.discard(lemma)
        print(f"Erzeuge Datensatz mit {args.model}: {lemma}")
        try:
            payload = generate_validated_payload(
                client,
                args.model,
                lemma,
                allowed_targets,
                max_attempts=max(1, args.max_attempts),
            )
            json_file = write_payload(import_dir, payload)
            payloads[lemma] = payload
            print(f"Gespeichert: {json_file}")
        except UnsupportedWordTypeError as exc:
            payload = build_unsupported_word_payload(exc.lemma, exc.part_of_speech, exc.reasoning)
            json_file = write_payload(import_dir, payload)
            print(f"Gespeichert als nicht unterstuetzte Wortart: {json_file}")
            continue
        except Exception as exc:  # pragma: no cover - Laufzeitverhalten gegen externe API.
            failures.append((lemma, str(exc)))
            print(f"Fehler bei {lemma}: {exc}", file=sys.stderr)
            continue

    if args.dry_run or not payloads:
        if failures:
            print(f"Fertig ohne Datenbankimport. Fehler bei {len(failures)} Woertern.", file=sys.stderr)
            for lemma, message in failures:
                print(f"- {lemma}: {message}", file=sys.stderr)
            return 1
        print("Fertig ohne Datenbankimport.")
        return 0

    with get_connection(str(database_path)) as connection:
        for payload in payloads.values():
            insert_word(connection, payload)
        insert_relations(connection, payloads)
        connection.commit()

    print(f"Import abgeschlossen: {len(payloads)} neue oder aktualisierte Woerter in {database_path}")
    if failures:
        print(f"Es gab Fehler bei {len(failures)} Woertern:", file=sys.stderr)
        for lemma, message in failures:
            print(f"- {lemma}: {message}", file=sys.stderr)
        return 1
    return 0


def build_unsupported_word_payload(lemma, part_of_speech, reasoning):
    return {
        "lemma": lemma,
        "wortart": part_of_speech,
        "silben": lemma,
        "beispielsatz": "",
        "begriffserklaerung": "",
        "rechtschreibstrategie": "",
        "rechtschreibkategorien": ["Mitsprechwort"],
        "bild_datei": f"{lemma}.webp",
        "audio_datei": f"{lemma}.mp3",
        "uebersetzungen": [],
        "beziehungen": [],
        "grammatische_formen": {},
        "fehlschreibungen": [],
        "wortart_pruefung": {
            "detected_wortart": part_of_speech,
            "begruendung": reasoning,
            "supported_for_import": False,
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
