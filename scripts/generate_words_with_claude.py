#!/usr/bin/env python3
"""
Erzeugt Wörterbuchdaten aus einer Wortliste mit der Claude API und importiert sie in SQLite.

Verwendet Tool Use für strukturierte JSON-Ausgabe und Prompt Caching.
Voraussetzung: ANTHROPIC_API_KEY als Umgebungsvariable setzen.
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from grundschul_woerterbuch.db import get_connection, init_db
from scripts.import_words import insert_relations, insert_word, validate_payload

try:
    import anthropic
except ImportError:
    anthropic = None


ALL_WORD_TYPES = {
    "Nomen", "Verb", "Adjektiv", "Adverb", "Pronomen",
    "Präposition", "Konjunktion", "Interjektion", "Numerale",
    "Artikel", "Partikel",
}
GRAMMAR_WORD_TYPES = {"Nomen", "Verb", "Adjektiv"}
DEFAULT_MODEL = "claude-sonnet-4-6"

SYSTEM_LEXICOGRAPHER = (
    "Du bist Lexikograf für ein kindgerechtes Grundschul-Wörterbuch. "
    "Formuliere alle Texte kurz, freundlich und für Kinder zwischen 7 und 12 Jahren verständlich. "
    "Verwende immer echte deutsche Zeichen: ä, ö, ü und ß."
)

SYSTEM_LINGUIST = "Du bist Linguist für deutsche Grammatik. Bestimme Wortarten präzise."


# ── Schemas ───────────────────────────────────────────────────────────────────

SCHEMA = {
    "type": "object",
    "properties": {
        "lemma": {"type": "string", "description": "Das Grundwort."},
        "wortart": {
            "type": "string",
            "enum": [
                "Nomen", "Verb", "Adjektiv", "Adverb", "Pronomen",
                "Präposition", "Konjunktion", "Interjektion", "Numerale",
                "Artikel", "Partikel",
            ],
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
            "description": "Gemeinsame Basen der Wortfamilie.",
        },
        "bild_datei": {"type": "string"},
        "audio_datei": {"type": "string"},
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
            "description": "Uebersetzungen fuer en, fr, tr und ar.",
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
        },
        "grammatische_formen": {
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
                        "ich": {"type": "string"}, "du": {"type": "string"},
                        "er_sie_es": {"type": "string"}, "wir": {"type": "string"},
                        "ihr": {"type": "string"}, "sie": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "perfekt": {
                    "type": "object",
                    "properties": {
                        "ich": {"type": "string"}, "du": {"type": "string"},
                        "er_sie_es": {"type": "string"}, "wir": {"type": "string"},
                        "ihr": {"type": "string"}, "sie": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "praeteritum": {
                    "type": "object",
                    "properties": {
                        "ich": {"type": "string"}, "du": {"type": "string"},
                        "er_sie_es": {"type": "string"}, "wir": {"type": "string"},
                        "ihr": {"type": "string"}, "sie": {"type": "string"},
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
        },
    },
    "required": [
        "lemma", "wortart", "silben", "beispielsatz", "begriffserklaerung",
        "rechtschreibstrategie", "rechtschreibkategorien", "wortfamilie_basen",
        "bild_datei", "audio_datei", "uebersetzungen", "beziehungen",
        "grammatische_formen", "fehlschreibungen",
    ],
    "additionalProperties": False,
}

POS_CLASSIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "wortart": {
            "type": "string",
            "enum": [
                "Nomen", "Verb", "Adjektiv", "Adverb", "Pronomen",
                "Präposition", "Konjunktion", "Interjektion", "Numerale",
                "Artikel", "Partikel",
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
                        "nominativ": {"type": "string"}, "genitiv": {"type": "string"},
                        "dativ": {"type": "string"}, "akkusativ": {"type": "string"},
                    },
                    "required": ["nominativ", "genitiv", "dativ", "akkusativ"],
                    "additionalProperties": False,
                },
                "plural": {
                    "type": "object",
                    "properties": {
                        "nominativ": {"type": "string"}, "genitiv": {"type": "string"},
                        "dativ": {"type": "string"}, "akkusativ": {"type": "string"},
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
                "ich": {"type": "string"}, "du": {"type": "string"},
                "er_sie_es": {"type": "string"}, "wir": {"type": "string"},
                "ihr": {"type": "string"}, "sie": {"type": "string"},
            },
            "required": ["ich", "du", "er_sie_es", "wir", "ihr", "sie"],
            "additionalProperties": False,
        },
        "perfekt": {
            "type": "object",
            "properties": {
                "ich": {"type": "string"}, "du": {"type": "string"},
                "er_sie_es": {"type": "string"}, "wir": {"type": "string"},
                "ihr": {"type": "string"}, "sie": {"type": "string"},
            },
            "required": ["ich", "du", "er_sie_es", "wir", "ihr", "sie"],
            "additionalProperties": False,
        },
        "praeteritum": {
            "type": "object",
            "properties": {
                "ich": {"type": "string"}, "du": {"type": "string"},
                "er_sie_es": {"type": "string"}, "wir": {"type": "string"},
                "ihr": {"type": "string"}, "sie": {"type": "string"},
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

# Tool-Definitionen
WORD_ENTRY_TOOL = {
    "name": "create_word_entry",
    "description": "Erstellt einen vollständigen Wörterbucheintrag für ein deutsches Grundschulwort.",
    "input_schema": SCHEMA,
}
POS_CLASSIFICATION_TOOL = {
    "name": "classify_part_of_speech",
    "description": "Bestimmt die Wortart eines deutschen Wortes.",
    "input_schema": POS_CLASSIFICATION_SCHEMA,
}
NOUN_GRAMMAR_TOOL = {
    "name": "provide_noun_grammar",
    "description": "Liefert die grammatischen Formen eines deutschen Nomens.",
    "input_schema": NOUN_GRAMMAR_SCHEMA,
}
VERB_GRAMMAR_TOOL = {
    "name": "provide_verb_grammar",
    "description": "Liefert die grammatischen Formen eines deutschen Verbs.",
    "input_schema": VERB_GRAMMAR_SCHEMA,
}
ADJECTIVE_GRAMMAR_TOOL = {
    "name": "provide_adjective_grammar",
    "description": "Liefert die grammatischen Formen eines deutschen Adjektivs.",
    "input_schema": ADJECTIVE_GRAMMAR_SCHEMA,
}


# ── Argument-Parser ───────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Erzeugt Wörterbuchdaten mit der Claude API und importiert sie in SQLite."
    )
    parser.add_argument("word_list", help="Textdatei mit einem Wort pro Zeile")
    parser.add_argument(
        "--database",
        default=str(ROOT_DIR / "data" / "grundschul_woerterbuch.sqlite3"),
    )
    parser.add_argument(
        "--import-dir",
        default=str(ROOT_DIR / "data" / "import_words"),
    )
    parser.add_argument(
        "--model", default=DEFAULT_MODEL,
        help=f"Claude-Modell-ID (Standard: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--skip-existing", action="store_true",
        help="Überspringt Wörter, die bereits in der Datenbank vorhanden sind.",
    )
    parser.add_argument(
        "--overwrite-json", action="store_true",
        help="Erzeugt JSON-Dateien neu, auch wenn bereits eine existiert.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Erzeugt nur JSON-Dateien, importiert nicht in die Datenbank.",
    )
    parser.add_argument(
        "--max-attempts", type=int, default=3,
        help="Maximale Versuche pro Wort bei Validierungsfehlern (nur ohne --batch).",
    )
    parser.add_argument(
        "--batch", action="store_true",
        help="Nutzt die Batch API (50%% Rabatt, asynchron, keine Wiederholungsversuche).",
    )
    parser.add_argument(
        "--resume-batch",
        metavar="BATCH_ID",
        help="Ruft Ergebnisse eines bereits abgeschlossenen Haupt-Batches ab (z.B. msgbatch_...).",
    )
    return parser.parse_args()


# ── Hilfsfunktionen (identisch zur Gemini-Version) ───────────────────────────

def slugify(value):
    value = value.strip().lower()
    for old, new in {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}.items():
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
    removable = {
        "der", "die", "das", "dem", "den", "des",
        "ein", "eine", "einen", "einem", "einer", "eines",
    }
    if words[0].lower() in removable:
        return " ".join(words[1:]).strip()
    return text.strip()


def get_existing_lemmas(database_path):
    init_db(str(database_path))
    with get_connection(str(database_path)) as conn:
        rows = conn.execute("SELECT lemma FROM words ORDER BY lemma").fetchall()
    return [row["lemma"] for row in rows]


def build_prompt(lemma, part_of_speech, allowed_targets, extra_instructions=""):
    prompt = f"""
Erzeuge genau einen JSON-Datensatz fuer ein kindgerechtes Grundschul-Woerterbuch.

Wort: {lemma}
Vorgegebene Wortart: {part_of_speech}

Wichtige Regeln:
- Schreibe alles auf Deutsch.
- Erhalte in allen fuer Kinder sichtbaren Texten die echten deutschen Zeichen: ä, ö, ü und ß.
- Formuliere kurz, freundlich und fuer Grundschulkinder verstaendlich.
- Verwende bei 'silben' Bindestriche zwischen den Silben.
- Nutze nur die Beziehungstypen word_family, word_field und synonym.
- Wenn du unsicher bist, gib bei 'beziehungen' lieber eine leere Liste zurueck.
- Verwende 'word_family' nur bei echter Wortverwandtschaft (gleicher Wortstamm oder klare Ableitung).
- Bevorzuge bei 'word_family' die gemeinsame Stammform statt einzelner Ableitungen.
- Trage die Wortfamilien zusaetzlich in 'wortfamilie_basen' ein.
- Verwende 'synonym' nur fuer sinnverwandte Woerter, die Kinder zwischen 7 und 12 Jahren verstehen.
- Verwende 'word_field' fuer thematisch zusammengehoerige Woerter (0 bis 3 Ziele).
- Nutze fuer 'bild_datei' genau {lemma}.webp und fuer 'audio_datei' genau {lemma}.mp3
- Liefere einige typische Kinderfehlschreibungen.
- Fuelle nur die grammatischen Formen passend zur Wortart sinnvoll.
- Setze bei 'wortart' genau den vorgegebenen Wert {part_of_speech}.
- Bei Nomen: 'grammatische_formen' muss 'deklination' mit Nominativ, Genitiv, Dativ, Akkusativ in Singular und Plural enthalten.
- Bei Verben: 'grammatische_formen' muss 'praesens', 'perfekt' und 'praeteritum' mit allen Personalformen enthalten.
- Ordne das Wort in Rechtschreibkategorien ein:
  - Wort mit Kürzezeichen: Doppelkonsonant, ck oder tz nach kurzem Vokal
  - Verlängerungswort: Verlängern macht die Schreibung sichtbar (z.B. Hund→Hunde)
  - Ableitungswort: verwandtes Wort erklaert die Schreibung
  - Mitsprechwort: nur wenn kein anderes Phaenomen passt
  - Bausteinwort: Zusammensetzungen
  - Merkwort mit Dehnungs-h, ß, ie, V, X, Qu, doppeltem Vokal: bei entsprechendem Phaenomen
- Jedes Wort muss mindestens eine Kategorie bekommen.

Uebersetzungen muessen fuer en, fr, tr und ar enthalten sein.
""".strip()
    if extra_instructions:
        prompt += f"\n\nKorrigiere besonders diese Punkte:\n{extra_instructions.strip()}"
    return prompt


def sanitize_payload(payload, requested_lemma, allowed_targets):
    payload["lemma"] = requested_lemma
    payload["bild_datei"] = f"{requested_lemma}.webp"
    payload["audio_datei"] = f"{requested_lemma}.mp3"

    filtered_relations = []
    relation_counts = {"word_family": 0, "word_field": 0, "synonym": 0}
    for relation in payload.get("beziehungen", []):
        if not isinstance(relation, dict):
            continue
        relation_type = relation.get("relation_type")
        target_lemma = str(relation.get("target_lemma", "")).strip()
        if (relation_type in {"word_family", "word_field", "synonym"}
                and target_lemma and target_lemma != requested_lemma):
            if relation_type == "word_field" and relation_counts["word_field"] >= 3:
                continue
            filtered_relations.append({"relation_type": relation_type, "target_lemma": target_lemma})
            relation_counts[relation_type] += 1
    payload["beziehungen"] = filtered_relations

    family_bases = []
    seen = set()
    for base in payload.get("wortfamilie_basen", []):
        cleaned = re.sub(r"\s+", " ", str(base).strip())
        if cleaned and cleaned.casefold() not in seen:
            family_bases.append(cleaned)
            seen.add(cleaned.casefold())
    payload["wortfamilie_basen"] = family_bases

    categories = []
    seen_cat = set()
    for cat in payload.get("rechtschreibkategorien", []):
        cleaned = str(cat).strip()
        if cleaned and cleaned not in seen_cat:
            categories.append(cleaned)
            seen_cat.add(cleaned)
    if len(categories) > 1 and "Mitsprechwort" in categories:
        categories = [c for c in categories if c != "Mitsprechwort"]
    if not categories:
        categories = ["Mitsprechwort"]
    payload["rechtschreibkategorien"] = categories

    for key in ["silben", "beispielsatz", "begriffserklaerung", "rechtschreibstrategie"]:
        if key in payload and isinstance(payload[key], str):
            payload[key] = payload[key].strip()

    grammar = strip_nested_strings(payload.get("grammatische_formen", {}))
    payload["grammatische_formen"] = sanitize_grammar_for_part_of_speech(
        grammar, payload.get("wortart"), requested_lemma
    )
    payload["rechtschreibkategorien"] = apply_spelling_heuristics(
        payload["lemma"], payload.get("wortart"),
        payload["grammatische_formen"], payload["rechtschreibkategorien"],
    )

    translations = []
    seen_lang = set()
    for item in payload.get("uebersetzungen", []):
        if not isinstance(item, dict):
            continue
        lang = str(item.get("language_code", "")).strip().lower()
        trans = str(item.get("translation", "")).strip()
        if lang and trans and lang not in seen_lang:
            translations.append({"language_code": lang, "translation": trans})
            seen_lang.add(lang)
    payload["uebersetzungen"] = translations

    misspellings = []
    seen_ms = set()
    for item in payload.get("fehlschreibungen", []):
        normalized = str(item).strip()
        if normalized and normalized.lower() not in seen_ms:
            misspellings.append(normalized)
            seen_ms.add(normalized.lower())
    payload["fehlschreibungen"] = misspellings
    return payload


def strip_nested_strings(value):
    if isinstance(value, dict):
        return {k: strip_nested_strings(v) for k, v in value.items()}
    if isinstance(value, list):
        return [strip_nested_strings(v) for v in value]
    if isinstance(value, str):
        return value.strip()
    return value


def sanitize_grammar_for_part_of_speech(grammar, part_of_speech, requested_lemma):
    if not isinstance(grammar, dict):
        grammar = {}

    if part_of_speech == "Nomen":
        deklination = grammar.get("deklination", {})
        sg = deklination.get("singular", {}) if isinstance(deklination, dict) else {}
        pl = deklination.get("plural", {}) if isinstance(deklination, dict) else {}
        article = grammar.get("artikel", "") or extract_article_from_phrase(sg.get("nominativ", ""))
        singular = grammar.get("singular", "") or extract_noun_from_phrase(sg.get("nominativ", "")) or requested_lemma
        plural = grammar.get("plural", "") or extract_noun_from_phrase(pl.get("nominativ", ""))
        inferred = build_noun_declension(article, singular, plural)
        return {
            "artikel": article,
            "singular": singular,
            "plural": plural,
            "deklination": {
                "singular": {
                    "nominativ": sg.get("nominativ", inferred["singular"]["nominativ"]),
                    "genitiv": sg.get("genitiv", inferred["singular"]["genitiv"]),
                    "dativ": sg.get("dativ", inferred["singular"]["dativ"]),
                    "akkusativ": sg.get("akkusativ", inferred["singular"]["akkusativ"]),
                },
                "plural": {
                    "nominativ": pl.get("nominativ", inferred["plural"]["nominativ"]),
                    "genitiv": pl.get("genitiv", inferred["plural"]["genitiv"]),
                    "dativ": pl.get("dativ", inferred["plural"]["dativ"]),
                    "akkusativ": pl.get("akkusativ", inferred["plural"]["akkusativ"]),
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
    normalized = list(categories)
    category_set = set(normalized)
    if looks_like_verlaengerungswort((lemma or "").lower(), part_of_speech, grammar):
        category_set.add("Verlängerungswort")
    if len(category_set) > 1 and "Mitsprechwort" in category_set:
        category_set.remove("Mitsprechwort")
    ordered = [c for c in normalized if c in category_set]
    for c in sorted(category_set):
        if c not in ordered:
            ordered.append(c)
    return ordered


def looks_like_verlaengerungswort(lemma_lower, part_of_speech, grammar):
    if not lemma_lower.endswith(("d", "b", "g")):
        return False
    comparison = []
    if part_of_speech == "Nomen":
        comparison += [
            grammar.get("plural", ""),
            grammar.get("deklination", {}).get("plural", {}).get("nominativ", ""),
            grammar.get("deklination", {}).get("singular", {}).get("genitiv", ""),
        ]
    elif part_of_speech == "Adjektiv":
        comparison += [grammar.get("komparativ", ""), grammar.get("superlativ", "")]
    elif part_of_speech == "Verb":
        comparison += [
            grammar.get("praesens", {}).get("ich", ""),
            grammar.get("praesens", {}).get("du", ""),
            grammar.get("praeteritum", {}).get("ich", ""),
        ]
    return any(comparison)


def pick_person_table(source):
    if not isinstance(source, dict):
        source = {}
    return {p: source.get(p, "") for p in ("ich", "du", "er_sie_es", "wir", "ihr", "sie")}


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
    arts = {
        "der": {"nominativ": "der", "genitiv": "des", "dativ": "dem", "akkusativ": "den"},
        "das": {"nominativ": "das", "genitiv": "des", "dativ": "dem", "akkusativ": "das"},
        "die": {"nominativ": "die", "genitiv": "der", "dativ": "der", "akkusativ": "die"},
    }.get(article_lower, {"nominativ": "das", "genitiv": "des", "dativ": "dem", "akkusativ": "das"})
    gen_sg = build_genitive_singular(article_lower, singular)
    dat_pl = build_dative_plural(plural)
    return {
        "singular": {
            "nominativ": join_phrase(arts["nominativ"], singular),
            "genitiv": join_phrase(arts["genitiv"], gen_sg),
            "dativ": join_phrase(arts["dativ"], singular),
            "akkusativ": join_phrase(arts["akkusativ"], singular),
        },
        "plural": {
            "nominativ": join_phrase("die", plural),
            "genitiv": join_phrase("der", plural),
            "dativ": join_phrase("den", dat_pl),
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
    if not plural or plural.lower().endswith(("n", "s")):
        return plural
    return f"{plural}n"


def join_phrase(article, noun):
    article = (article or "").strip()
    noun = (noun or "").strip()
    if article and noun:
        return f"{article} {noun}"
    return article or noun


def write_payload(import_dir, payload):
    filename = import_dir / f"{slugify(payload['lemma'])}.json"
    filename.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return filename


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


# ── Claude API ────────────────────────────────────────────────────────────────

def build_client():
    if anthropic is None:
        raise RuntimeError(
            "Das Paket 'anthropic' fehlt. Bitte installieren:\n  pip install anthropic"
        )
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY ist nicht gesetzt.\n"
            "  export ANTHROPIC_API_KEY=sk-ant-..."
        )
    return anthropic.Anthropic(api_key=api_key)


def _call_tool(client, model, system, user_content, tool, max_tokens):
    """Führt einen Tool-Use-Aufruf durch und gibt das Tool-Input-Dict zurück."""
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_content}],
        tools=[{**tool, "cache_control": {"type": "ephemeral"}}],
        tool_choice={"type": "tool", "name": tool["name"]},
    )
    tool_block = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_block is None:
        raise ValueError(f"Kein Tool-Ergebnis für '{tool['name']}' erhalten.")
    return tool_block.input


def classify_part_of_speech(client, model, lemma):
    prompt = (
        f"Bestimme die Wortart des deutschen Wortes '{lemma}'.\n\n"
        "Erlaubte Wortarten: Nomen, Verb, Adjektiv, Adverb, Pronomen, "
        "Präposition, Konjunktion, Interjektion, Numerale, Artikel, Partikel.\n\n"
        "Wichtige Regeln:\n"
        "- 'Adjektiv' nur bei echten Eigenschaftswörtern, die gesteigert werden können.\n"
        "- 'Nomen' nur bei Wörtern mit Artikel (Ding, Lebewesen, Begriff, Name).\n"
        "- 'Verb' nur bei Infinitiven oder klaren Verbgrundformen.\n"
        "- Kein Wort aus Verlegenheit als Adjektiv einordnen."
    )
    result = _call_tool(client, model, SYSTEM_LINGUIST, prompt,
                        POS_CLASSIFICATION_TOOL, max_tokens=256)
    return result["wortart"], result.get("begruendung", "")


def request_payload(client, model, lemma, part_of_speech, allowed_targets, extra_instructions=""):
    prompt = build_prompt(lemma, part_of_speech, allowed_targets, extra_instructions)
    return _call_tool(client, model, SYSTEM_LEXICOGRAPHER, prompt,
                      WORD_ENTRY_TOOL, max_tokens=2048)


def request_grammar_section(client, model, lemma, part_of_speech):
    if part_of_speech == "Nomen":
        tool = NOUN_GRAMMAR_TOOL
        prompt = (
            f"Erzeuge die vollständigen grammatischen Formen des Nomens '{lemma}'. "
            "Liefere artikel, singular, plural und deklination mit allen vier Fällen "
            "in Singular und Plural. Nutze echte deutsche Umlaute und ß."
        )
    elif part_of_speech == "Verb":
        tool = VERB_GRAMMAR_TOOL
        prompt = (
            f"Erzeuge die vollständigen grammatischen Formen des Verbs '{lemma}'. "
            "Liefere infinitiv, praesens, perfekt und praeteritum mit allen "
            "Personalformen (ich, du, er_sie_es, wir, ihr, sie). "
            "Nutze echte deutsche Umlaute und ß."
        )
    else:
        tool = ADJECTIVE_GRAMMAR_TOOL
        prompt = (
            f"Erzeuge die grammatischen Formen des Adjektivs '{lemma}'. "
            "Liefere positiv, komparativ und superlativ. Nutze echte deutsche Umlaute und ß."
        )
    return _call_tool(client, model, SYSTEM_LEXICOGRAPHER, prompt, tool, max_tokens=512)


# ── Generierungs-Logik ────────────────────────────────────────────────────────

def generate_validated_payload(client, model, lemma, allowed_targets, max_attempts):
    part_of_speech, _ = classify_part_of_speech(client, model, lemma)

    extra_instructions = ""
    last_errors = []
    last_payload = None

    for attempt in range(1, max_attempts + 1):
        payload = request_payload(client, model, lemma, part_of_speech,
                                  allowed_targets, extra_instructions=extra_instructions)
        last_payload = payload
        payload = sanitize_payload(payload, lemma, allowed_targets)
        payload["wortart"] = part_of_speech
        errors = validate_payload(payload, f"{lemma}.json")
        if not errors:
            return payload

        last_errors = errors
        error_lines = "\n".join(f"- {e}" for e in errors)
        extra_instructions = (
            f"Dies ist Versuch {attempt + 1} von {max_attempts}. "
            f"Bitte behebe diese Fehler:\n{error_lines}"
        )

    if part_of_speech in GRAMMAR_WORD_TYPES:
        repaired = try_sectional_repair(client, model, lemma, allowed_targets,
                                        last_payload or {}, part_of_speech)
        if repaired is not None:
            errors = validate_payload(repaired, f"{lemma}.json")
            if not errors:
                return repaired
            last_errors = errors

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


# ── Sequenzielle Verarbeitung ─────────────────────────────────────────────────

def run_sequential(client, model, words, existing_lemmas, all_words,
                   import_dir, dry_run, max_attempts):
    all_targets = set(existing_lemmas).union(all_words)
    payloads = {}
    failures = []

    for lemma in words:
        allowed_targets = all_targets - {lemma}
        print(f"Erzeuge: {lemma}")
        try:
            payload = generate_validated_payload(
                client, model, lemma, allowed_targets, max_attempts
            )
            if not dry_run:
                json_file = write_payload(import_dir, payload)
                print(f"  Gespeichert: {json_file}")
            payloads[lemma] = payload
        except Exception as exc:
            failures.append((lemma, str(exc)))
            print(f"  Fehler: {exc}", file=sys.stderr)

    return payloads, failures


# ── Batch-API-Verarbeitung ────────────────────────────────────────────────────

def _unique_slug(base, existing: dict) -> str:
    slug = base
    i = 1
    while slug in existing:
        slug = f"{base}-{i}"
        i += 1
    return slug


def _wait_for_batch(client, batch):
    while batch.processing_status != "ended":
        counts = batch.request_counts
        print(
            f"  {counts.processing} aktiv · "
            f"{counts.succeeded} fertig · "
            f"{counts.errored} fehlerhaft"
        )
        time.sleep(30)
        batch = client.messages.batches.retrieve(batch.id)
    return batch


def run_batch(client, model, words, existing_lemmas, all_words, import_dir, dry_run):
    """Verarbeitet alle Wörter vollständig über die Batch API (50 % Rabatt, kein Retry)."""
    all_targets = set(existing_lemmas).union(all_words)

    # ── Schritt 1: POS-Klassifizierung als Batch ──────────────────────────────
    print(f"Sende POS-Klassifizierungs-Batch für {len(words)} Wörter ...")
    pos_classify_prompt = (
        "Bestimme die Wortart des deutschen Wortes '{lemma}'.\n\n"
        "Erlaubte Wortarten: Nomen, Verb, Adjektiv, Adverb, Pronomen, "
        "Präposition, Konjunktion, Interjektion, Numerale, Artikel, Partikel.\n\n"
        "Wichtige Regeln:\n"
        "- 'Adjektiv' nur bei echten Eigenschaftswörtern, die gesteigert werden können.\n"
        "- 'Nomen' nur bei Wörtern mit Artikel (Ding, Lebewesen, Begriff, Name).\n"
        "- 'Verb' nur bei Infinitiven oder klaren Verbgrundformen.\n"
        "- Kein Wort aus Verlegenheit als Adjektiv einordnen."
    )

    slug_to_lemma_pos: dict[str, str] = {}
    pos_requests = []
    for lemma in words:
        slug = _unique_slug(f"pos-{slugify(lemma)}", slug_to_lemma_pos)
        slug_to_lemma_pos[slug] = lemma
        pos_requests.append({
            "custom_id": slug,
            "params": {
                "model": model,
                "max_tokens": 256,
                "system": [{"type": "text", "text": SYSTEM_LINGUIST,
                             "cache_control": {"type": "ephemeral"}}],
                "messages": [{"role": "user", "content": pos_classify_prompt.format(lemma=lemma)}],
                "tools": [{**POS_CLASSIFICATION_TOOL, "cache_control": {"type": "ephemeral"}}],
                "tool_choice": {"type": "tool", "name": "classify_part_of_speech"},
            },
        })

    pos_batch = client.messages.batches.create(requests=pos_requests)
    print(f"POS-Batch-ID: {pos_batch.id}. Warte auf Abschluss ...")
    pos_batch = _wait_for_batch(client, pos_batch)

    # ── Schritt 2: POS-Ergebnisse auswerten ──────────────────────────────────
    word_pos: dict[str, str] = {}
    failures: list[tuple[str, str]] = []
    for result in client.messages.batches.results(pos_batch.id):
        lemma = slug_to_lemma_pos.get(result.custom_id, result.custom_id)
        if result.result.type != "succeeded":
            failures.append((lemma, str(getattr(result.result, "error", "POS-Fehler"))))
            continue
        tool_block = next(
            (b for b in result.result.message.content if b.type == "tool_use"), None
        )
        if tool_block is None:
            failures.append((lemma, "Kein POS-Tool-Ergebnis"))
            continue
        word_pos[lemma] = tool_block.input["wortart"]

    print(f"  {len(word_pos)} Wortarten ermittelt, {len(failures)} Fehler.")
    if not word_pos:
        return {}, failures

    # ── Schritt 3: Hauptgenerierung als Batch ─────────────────────────────────
    print(f"\nSende Hauptgenerierungs-Batch mit {len(word_pos)} Anfragen ...")
    slug_to_lemma_main: dict[str, str] = {}
    main_requests = []
    for lemma, pos in word_pos.items():
        slug = _unique_slug(slugify(lemma), slug_to_lemma_main)
        slug_to_lemma_main[slug] = lemma
        allowed_targets = all_targets - {lemma}
        main_requests.append({
            "custom_id": slug,
            "params": {
                "model": model,
                "max_tokens": 2048,
                "system": [{"type": "text", "text": SYSTEM_LEXICOGRAPHER,
                             "cache_control": {"type": "ephemeral"}}],
                "messages": [{"role": "user", "content": build_prompt(lemma, pos, allowed_targets)}],
                "tools": [{**WORD_ENTRY_TOOL, "cache_control": {"type": "ephemeral"}}],
                "tool_choice": {"type": "tool", "name": "create_word_entry"},
            },
        })

    main_batch = client.messages.batches.create(requests=main_requests)
    print(f"Haupt-Batch-ID: {main_batch.id}. Warte auf Abschluss ...")
    main_batch = _wait_for_batch(client, main_batch)

    # ── Schritt 4: Ergebnisse verarbeiten ─────────────────────────────────────
    payloads = {}
    for result in client.messages.batches.results(main_batch.id):
        lemma = slug_to_lemma_main.get(result.custom_id, result.custom_id)
        if result.result.type != "succeeded":
            failures.append((lemma, str(getattr(result.result, "error", "Unbekannter Fehler"))))
            continue
        tool_block = next(
            (b for b in result.result.message.content if b.type == "tool_use"), None
        )
        if tool_block is None:
            failures.append((lemma, "Kein Tool-Ergebnis in der Antwort"))
            continue
        payload = sanitize_payload(dict(tool_block.input), lemma, set())
        payload["wortart"] = word_pos[lemma]
        errors = validate_payload(payload, f"{lemma}.json")
        if errors:
            failures.append((lemma, "; ".join(errors)))
        else:
            if not dry_run:
                write_payload(import_dir, payload)
            payloads[lemma] = payload

    print(f"\n{len(payloads)} Wörter erfolgreich, {len(failures)} Fehler.")
    return payloads, failures


# ── Batch-Ergebnisse abrufen ──────────────────────────────────────────────────

def resume_batch(client, batch_id, import_dir, dry_run):
    """Verarbeitet die Ergebnisse eines bereits abgeschlossenen Haupt-Batches."""
    print(f"Rufe Ergebnisse für Batch {batch_id} ab ...")
    payloads = {}
    failures = []
    for result in client.messages.batches.results(batch_id):
        if result.result.type != "succeeded":
            error = getattr(result.result, "error", "Unbekannter Fehler")
            failures.append((result.custom_id, str(error)))
            continue
        tool_block = next(
            (b for b in result.result.message.content if b.type == "tool_use"), None
        )
        if tool_block is None:
            failures.append((result.custom_id, "Kein Tool-Ergebnis"))
            continue

        raw = dict(tool_block.input)
        lemma = raw.get("lemma", "").strip()
        if not lemma:
            failures.append((result.custom_id, "Kein Lemma im Tool-Ergebnis"))
            continue

        payload = sanitize_payload(raw, lemma, set())
        errors = validate_payload(payload, f"{lemma}.json")
        if errors:
            failures.append((lemma, "; ".join(errors)))
            print(f"  Validierungsfehler bei {lemma}: {'; '.join(errors)}", file=sys.stderr)
        else:
            if not dry_run:
                write_payload(import_dir, payload)
            payloads[lemma] = payload
            print(f"  OK: {lemma}")

    print(f"\n{len(payloads)} Wörter erfolgreich, {len(failures)} Fehler.")
    return payloads, failures


# ── Einstiegspunkt ────────────────────────────────────────────────────────────

def main():
    args = parse_args()

    if anthropic is None:
        print("Das Paket 'anthropic' fehlt. Bitte 'pip install anthropic' ausfuehren.",
              file=sys.stderr)
        return 1

    try:
        client = build_client()
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

    all_words = load_words(word_list_path)
    existing_lemmas = set(get_existing_lemmas(database_path))

    words = []
    for lemma in all_words:
        json_file = import_dir / f"{slugify(lemma)}.json"
        if json_file.exists() and not args.overwrite_json:
            print(f"Ueberspringe vorhandene JSON-Datei: {json_file}")
            continue
        if args.skip_existing and lemma in existing_lemmas:
            print(f"Ueberspringe bestehendes Wort: {lemma}")
            continue
        words.append(lemma)

    if args.resume_batch:
        payloads, failures = resume_batch(client, args.resume_batch, import_dir, args.dry_run)
    else:
        if not words:
            print("Keine neuen Wörter zu verarbeiten.")
            return 0

        print(f"Modell: {args.model}")
        print(f"Modus:  {'Batch API' if args.batch else 'Sequenziell'}")
        print(f"Wörter: {len(words)}")

        if args.batch:
            payloads, failures = run_batch(
                client, args.model, words, existing_lemmas, all_words,
                import_dir, args.dry_run,
            )
        else:
            payloads, failures = run_sequential(
                client, args.model, words, existing_lemmas, all_words,
                import_dir, args.dry_run, args.max_attempts,
            )

    if failures:
        print(f"\n{len(failures)} Fehler:", file=sys.stderr)
        for lemma, msg in failures:
            print(f"  - {lemma}: {msg}", file=sys.stderr)

    if args.dry_run or not payloads:
        print(f"\nFertig (ohne Datenbankimport). {len(payloads)} Dateien erzeugt.")
        return 1 if failures else 0

    with get_connection(str(database_path)) as conn:
        for payload in payloads.values():
            insert_word(conn, payload)
        insert_relations(conn, payloads)
        conn.commit()

    print(f"\nImport abgeschlossen: {len(payloads)} Wörter in {database_path}.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
