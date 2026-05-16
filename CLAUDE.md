# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Grundschul-Wörterbuch — a Flask-based children's dictionary prototype with text search, handwriting analysis, and SQLite as the primary data store. Content is generated via Gemini (Vertex AI) and imported as JSON.

## Commands

```bash
# Install dependencies
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run the app (port 5005, set via .flaskenv)
flask --app app run --debug

# Rebuild the database from JSON files in data/import_words/
python3 scripts/import_words.py --rebuild

# Generate word entries via Gemini (Vertex AI key.json or GEMINI_API_KEY)
python3 scripts/generate_words_with_gemini.py woerterliste.txt --skip-existing
python3 scripts/generate_words_with_gemini.py woerterliste.txt --dry-run  # JSON only, no DB import

# Review and fix word types in existing JSON files
python3 scripts/check_word_types_with_gemini.py --credentials-file key.json
python3 scripts/check_word_types_with_gemini.py --credentials-file key.json --apply
```

## Architecture

**App factory** (`grundschul_woerterbuch/__init__.py`): `create_app()` instantiates all services and stores them in `app.extensions` (not `g`). Routes access services via `current_app.extensions["service_name"]`.

**Service layer** (`grundschul_woerterbuch/services/`):
- `SearchService` — four-stage search: exact normalized match → misspelling match → prefix match → fuzzy (rapidfuzz). Normalization maps ä→ae, ö→oe, ü→ue, ß→ss, strips non-alphanumeric. The full word list for fuzzy search is lazy-loaded and cached in `_search_terms_cache`; call `invalidate_cache()` after a DB import.
- `build_handwriting_service()` — factory returning a `GeminiHandwritingService` (Vertex AI vision) or `MockHandwritingService`. Falls back to mock silently if credentials fail. `enrich_handwriting_analysis(raw, repository, search_service)` is a module-level function in the same file that resolves each detected error against the dictionary; the route layer adds `word_url` afterwards.
- `JsonReviewService` — manages the review queue of pending JSON files in `data/import_words/` before they are imported.

**Repository** (`grundschul_woerterbuch/repository.py`): `WordRepository` handles all SQLite queries. `get_word_details()` assembles the full word object including translations, relations, grammatical forms, and word-family boxes.

**Database** (`grundschul_woerterbuch/db.py`): Schema is applied via `init_db()` on every app start (idempotent). `ensure_column()` handles additive migrations without dropping data.

**Routes** (`grundschul_woerterbuch/routes.py`): A Flask `Blueprint("main", __name__)` named `bp` is registered in `create_app()`. All `url_for` calls use the `main.` prefix (e.g. `url_for('main.word_page', lemma=...)`). Key endpoints:
- `GET /` — home with search
- `GET /search?q=` — resolves query and redirects to word page or returns suggestions
- `GET /word/<lemma>` — word detail page
- `GET /api/autocomplete?q=` — JSON suggestions (CORS enabled)
- `GET /api/word/<lemma>` — full word data as JSON, public API with CORS (`Access-Control-Allow-Origin: *`); internal DB fields (`id`, `normalized_lemma`, etc.) are excluded via `_public_word_payload()`
- `GET|POST /writing-check` — handwriting image upload and analysis
- `GET /review`, `GET /review/<slug>` — JSON entry review queue

## Data flow for new words

1. Gemini generates a JSON file per word into `data/import_words/` (German field names: `wortart`, `begriffserklaerung`, etc.)
2. Optional review via `/review` route (`JsonReviewService`)
3. `scripts/import_words.py --rebuild` imports all approved JSON into SQLite
4. Missing relation targets are collected in `data/missing_relation_words.txt` and `data/missing_relation_words_next.txt` (prioritized for the next Gemini run)

## Configuration

All runtime config is via environment variables (see `grundschul_woerterbuch/__init__.py` for defaults):

| Variable | Default | Effect |
|---|---|---|
| `HANDWRITING_MODE` | `gemini` | `gemini` or `mock` |
| `GEMINI_CREDENTIALS_FILE` | `./key.json` | Vertex AI service account file |

Vertex AI credentials are auto-detected from `./key.json`, `./key3.json`, `./scripts/key.json`, or `./scripts/key3.json`.

## Media files

Word pages expect `static/images/<WORT>.webp` and `static/audio/<WORT>.mp3`. Missing files are handled gracefully with placeholders. Uploaded handwriting images land in `static/uploads/`.

## Word types and normalization

Only `Nomen`, `Verb`, and `Adjektiv` are fully supported. Relation types are constrained to `word_family`, `word_field`, and `synonym` at the database level. Umlaut normalization is used for search indexing but German text (with Umlaute and ß) is preserved in all visible output.
