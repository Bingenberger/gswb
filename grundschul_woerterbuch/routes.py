import json
import secrets
from pathlib import Path

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from .services.handwriting_service import enrich_handwriting_analysis

bp = Blueprint("main", __name__)


@bp.after_request
def add_api_cors_headers(response):
    if request.endpoint in ("main.api_autocomplete", "main.api_word") and request.method in ("GET", "HEAD", "OPTIONS"):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET"
    return response


@bp.context_processor
def inject_helpers():
    return {
        "relation_labels": RELATION_LABELS,
        "translation_meta": TRANSLATION_META,
        "part_of_speech_meta": PART_OF_SPEECH_META,
        "suggestion_match_labels": SUGGESTION_MATCH_LABELS,
        "spelling_category_icons": SPELLING_CATEGORY_ICONS,
    }


@bp.route("/")
def home():
    repository = current_app.extensions["word_repository"]
    word_of_day_stub = repository.get_word_of_the_day()
    word_of_day = None
    if word_of_day_stub:
        word_of_day = repository.get_word_details(word_of_day_stub["lemma"])
        if word_of_day:
            word_of_day["syllable_parts"] = split_syllables(word_of_day.get("syllables"))
    return render_template("home.html", word_of_day=word_of_day)


@bp.route("/categories")
def categories():
    repository = current_app.extensions["word_repository"]
    all_categories = repository.get_all_spelling_categories()
    return render_template("categories.html", categories=all_categories)


@bp.route("/category/<category>")
def category_words(category):
    repository = current_app.extensions["word_repository"]
    words = repository.get_words_by_spelling_category(category)
    return render_template("category_words.html", category=category, words=words)


@bp.route("/writing-check", methods=["GET", "POST"])
def writing_check():
    analysis = None
    error_message = None
    handwriting_service = current_app.extensions["handwriting_service"]

    if request.method == "POST":
        upload = request.files.get("image")
        if not upload or not upload.filename:
            error_message = "Bitte wähle zuerst ein Bild aus."
        else:
            try:
                image_bytes = upload.read()
                if not image_bytes:
                    raise ValueError("Das Bild ist leer.")
                mime_type = upload.mimetype or "image/jpeg"
                filename, public_url = save_uploaded_image(
                    upload.filename, image_bytes, current_app.config["HANDWRITING_UPLOAD_DIR"]
                )
                repository = current_app.extensions["word_repository"]
                search_service = current_app.extensions["search_service"]
                raw_analysis = handwriting_service.analyze(image_bytes, mime_type)
                analysis = enrich_handwriting_analysis(raw_analysis, repository, search_service)
                for error in analysis["errors"]:
                    lemma = error.pop("word_lemma", None)
                    error["word_url"] = url_for("main.word_page", lemma=lemma) if lemma else None
                analysis["image_url"] = public_url
                analysis["stored_filename"] = filename
            except Exception as exc:
                error_message = str(exc)

    return render_template(
        "writing_check.html",
        analysis=analysis,
        analysis_json=json.dumps(analysis or {}, ensure_ascii=False),
        error_message=error_message,
        handwriting_mode=current_app.config.get("HANDWRITING_MODE", "mock"),
        handwriting_startup_warning=getattr(handwriting_service, "startup_warning", None),
        handwriting_requested_mode=getattr(
            handwriting_service, "requested_mode", current_app.config.get("HANDWRITING_MODE", "mock")
        ),
    )


@bp.route("/review")
def review_home():
    review_service = current_app.extensions["json_review_service"]
    next_slug = review_service.next_pending_slug()
    if not next_slug:
        return render_template("review_empty.html")
    return redirect(url_for("main.review_entry", slug=next_slug))


@bp.route("/review/<slug>")
def review_entry(slug):
    review_service = current_app.extensions["json_review_service"]
    entry = review_service.get_entry(slug)
    if not entry:
        return render_template("404.html", lemma=slug), 404
    return render_template("review_entry.html", entry=entry)


@bp.post("/review/<slug>/approve")
def review_approve(slug):
    review_service = current_app.extensions["json_review_service"]
    review_service.update_flags(slug, approved=True, needs_regeneration=False)
    next_slug = request.form.get("next_slug")
    return redirect(url_for("main.review_entry", slug=next_slug or slug))


@bp.post("/review/<slug>/toggle-regeneration")
def review_toggle_regeneration(slug):
    review_service = current_app.extensions["json_review_service"]
    entry = review_service.get_entry(slug)
    if not entry:
        return render_template("404.html", lemma=slug), 404
    review_service.update_flags(slug, needs_regeneration=not entry["review"]["needs_regeneration"])
    return redirect(url_for("main.review_entry", slug=slug))


@bp.post("/review/<slug>/save")
def review_save(slug):
    review_service = current_app.extensions["json_review_service"]
    raw_json = request.form.get("raw_json", "")
    try:
        review_service.save_payload(slug, raw_json)
    except ValueError as exc:
        entry = review_service.get_entry(slug)
        return render_template("review_entry.html", entry=entry, editor_error=str(exc), editor_text=raw_json), 400
    flash("Datensatz gespeichert.", "success")
    return redirect(url_for("main.review_entry", slug=slug))


@bp.route("/search")
def search():
    query = request.args.get("q", "").strip()
    if not query:
        return redirect(url_for("main.home"))

    search_service = current_app.extensions["search_service"]
    result = search_service.resolve_query(query)
    if result["match"]:
        return redirect(url_for("main.word_page", lemma=result["match"]["lemma"]))

    suggestions = search_service.autocomplete(query)
    return render_template("home.html", search_query=query, suggestions=suggestions, search_error=True)


@bp.route("/word/<lemma>")
def word_page(lemma):
    repository = current_app.extensions["word_repository"]
    word = repository.get_word_details(lemma)
    if not word:
        return render_template("404.html", lemma=lemma), 404

    word["syllable_parts"] = split_syllables(word.get("syllables"))
    word["relations_grouped"] = group_relations(word["relations"])
    return render_template("word.html", word=word)


@bp.route("/api/autocomplete")
def api_autocomplete():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"query": query, "suggestions": []})

    search_service = current_app.extensions["search_service"]
    suggestions = search_service.autocomplete(query)
    return jsonify({"query": query, "suggestions": suggestions})


@bp.route("/api/word/<lemma>")
def api_word(lemma):
    repository = current_app.extensions["word_repository"]
    word = repository.get_word_details(lemma)
    if not word:
        return jsonify({"error": "not_found"}), 404

    return jsonify(_public_word_payload(word))


SPELLING_CATEGORY_ICONS = {
    "Bausteinwort":               "rs_icons/Symbol Baustein.svg",
    "Mitsprechwort":              "rs_icons/Symbol Mitsprechwort.svg",
    "Wort mit Kürzezeichen":      "rs_icons/Symbol Kürzezeichen.svg",
    "Ableitungswort":             "rs_icons/Symbol Ableitung.svg",
    "Verlängerungswort":          "rs_icons/Symbol Verlängern.svg",
    "Merkwort mit ie":            "rs_icons/Symbol Merkwort.svg",
    "Merkwort mit Dehnungs-h":    "rs_icons/Symbol Merkwort.svg",
    "Merkwort mit doppeltem Vokal": "rs_icons/Symbol Merkwort.svg",
    "Merkwort mit V":             "rs_icons/Symbol Merkwort.svg",
    "Merkwort mit ß":             "rs_icons/Symbol Merkwort.svg",
    "Merkwort mit X":             "rs_icons/Symbol Merkwort.svg",
    "Merkwort mit Qu":            "rs_icons/Symbol Merkwort.svg",
    "Großschreibung":             "rs_icons/Symbol Großschreibung.svg",
}

RELATION_LABELS = {
    "word_family": "Wortfamilie",
    "word_field": "Wortfeld",
    "synonym": "Sinnverwandte Wörter",
}

TRANSLATION_META = {
    "en": {"label": "Englisch", "flag": "🇬🇧"},
    "fr": {"label": "Französisch", "flag": "🇫🇷"},
    "tr": {"label": "Türkisch", "flag": "🇹🇷"},
    "ar": {"label": "Arabisch", "flag": "🇸🇦"},
}

PART_OF_SPEECH_META = {
    "Nomen": {"label": "Nomen", "class_name": "is-noun"},
    "Verb": {"label": "Verb", "class_name": "is-verb"},
    "Adjektiv": {"label": "Adjektiv", "class_name": "is-adjective"},
    "Adverb": {"label": "Adverb", "class_name": "is-adverb"},
    "Pronomen": {"label": "Pronomen", "class_name": "is-pronoun"},
    "Präposition": {"label": "Präposition", "class_name": "is-preposition"},
    "Konjunktion": {"label": "Konjunktion", "class_name": "is-conjunction"},
    "Interjektion": {"label": "Interjektion", "class_name": "is-interjection"},
    "Numerale": {"label": "Numerale", "class_name": "is-numeral"},
    "Artikel": {"label": "Artikel", "class_name": "is-article"},
    "Partikel": {"label": "Partikel", "class_name": "is-particle"},
}

SUGGESTION_MATCH_LABELS = {
    "exact": "genau",
    "prefix": "beginnt so",
    "fehlschreibung": "fast richtig",
    "meintest-du": "meintest du?",
}


def split_syllables(syllables):
    if not syllables:
        return []
    return [part.strip() for part in syllables.split("-") if part.strip()]


def group_relations(relations):
    grouped = {key: [] for key in RELATION_LABELS}
    for relation in relations:
        grouped.setdefault(relation["relation_type"], []).append(relation["lemma"])
    return grouped


def _strip_internal(forms):
    if not forms:
        return None
    return {k: v for k, v in forms.items() if k != "word_id"}


def _public_word_payload(word):
    return {
        "lemma": word["lemma"],
        "part_of_speech": word["part_of_speech"],
        "syllables": word.get("syllables"),
        "syllable_parts": split_syllables(word.get("syllables")),
        "definition": word.get("definition"),
        "example_sentence": word.get("example_sentence"),
        "spelling_strategy": word.get("spelling_strategy"),
        "spelling_categories": word.get("spelling_categories", []),
        "translations": word.get("translations", []),
        "relations": word.get("relations", []),
        "relations_grouped": group_relations(word.get("relations", [])),
        "noun_forms": _strip_internal(word.get("noun_forms")),
        "verb_forms": _strip_internal(word.get("verb_forms")),
        "adjective_forms": _strip_internal(word.get("adjective_forms")),
        "word_family_boxes": word.get("word_family_boxes", []),
        "word_field_boxes": word.get("word_field_boxes", []),
    }


def save_uploaded_image(original_filename, image_bytes, upload_dir):
    upload_path = Path(upload_dir)
    upload_path.mkdir(parents=True, exist_ok=True)
    safe_name = secure_filename(original_filename) or "schreibprobe.jpg"
    extension = Path(safe_name).suffix.lower() or ".jpg"
    if extension not in {".jpg", ".jpeg", ".png", ".webp"}:
        extension = ".jpg"
    filename = f"{secrets.token_hex(8)}{extension}"
    (upload_path / filename).write_bytes(image_bytes)
    return filename, url_for("static", filename=f"uploads/{filename}")
