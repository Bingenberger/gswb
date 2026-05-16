import json
import os
import re
from pathlib import Path

try:
    from google import genai
    from google.genai import types
    from google.genai.types import HttpOptions
except ImportError:  # pragma: no cover - optional
    genai = None
    types = None
    HttpOptions = None


HANDWRITING_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "recognized_text": {"type": "string"},
        "errors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "written_word": {"type": "string"},
                    "correct_word": {"type": "string"},
                    "lemma": {"type": "string"},
                    "general_tip": {"type": "string"},
                    "category_hint": {"type": "string"},
                    "bbox": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "integer"},
                            "y": {"type": "integer"},
                            "width": {"type": "integer"},
                            "height": {"type": "integer"},
                        },
                        "required": ["x", "y", "width", "height"],
                        "additionalProperties": False,
                    },
                },
                "required": ["written_word", "correct_word", "lemma", "general_tip", "bbox"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["recognized_text", "errors"],
    "additionalProperties": False,
}


class HandwritingAnalysisService:
    def analyze(self, image_bytes, mime_type):  # pragma: no cover - interface
        raise NotImplementedError


class MockHandwritingAnalysisService(HandwritingAnalysisService):
    def analyze(self, image_bytes, mime_type):
        return {
            "mode": "mock",
            "recognized_text": "Der Hunt ist schnel.",
            "errors": [
                {
                    "written_word": "Hunt",
                    "correct_word": "Hund",
                    "lemma": "Hund",
                    "general_tip": "Sprich das Wort länger: Hunde. Dann hörst du das d.",
                    "category_hint": "Verlängerungswort",
                    "bbox": {"x": 260, "y": 270, "width": 150, "height": 90},
                },
                {
                    "written_word": "schnel",
                    "correct_word": "schnell",
                    "lemma": "schnell",
                    "general_tip": "Nach einem kurzen Vokal wird der Konsonant oft doppelt geschrieben.",
                    "category_hint": "Wort mit Kürzezeichen",
                    "bbox": {"x": 610, "y": 510, "width": 170, "height": 90},
                },
            ],
        }


class GeminiHandwritingAnalysisService(HandwritingAnalysisService):
    def __init__(self, model, credentials_file=None, location="global"):
        if genai is None or types is None or HttpOptions is None:
            raise RuntimeError("google-genai ist nicht installiert.")
        self.model = model
        self.auth_info = configure_genai_auth(credentials_file, location)
        if self.auth_info["mode"] == "api_key":
            self.client = genai.Client()
        else:
            self.client = genai.Client(http_options=HttpOptions(api_version="v1"))

    def analyze(self, image_bytes, mime_type):
        if not image_bytes:
            raise ValueError("Kein Bild empfangen.")

        prompt = """
Analysiere das Foto eines handgeschriebenen deutschen Kindertextes.

Ziele:
- Erkenne den Text so gut wie moeglich.
- Markiere nur Woerter, die sehr wahrscheinlich falsch geschrieben sind.
- Gib fuer jeden Fehler das falsch geschriebene Wort, das korrekt geschriebene Wort im Text, das passende Lemma
  und einen kurzen allgemeinen Tipp fuer Kinder zur Rechtschreibung an.
- Gib fuer jedes fehlerhafte Wort eine ungefaehre Bounding Box als normierte Ganzzahlen zwischen 0 und 1000 an.
- x und y sind die linke obere Ecke.
- width und height sind Breite und Hoehe.

Wichtige Regeln:
- Markiere nur echte Rechtschreibfehler, keine reinen Unsicherheiten.
- Halte die Zahl der Fehler klein und sinnvoll.
- Die Antwort muss reines JSON sein.
""".strip()

        part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        response = self.client.models.generate_content(
            model=self.model,
            contents=[prompt, part],
            config={
                "response_mime_type": "application/json",
                "response_json_schema": HANDWRITING_ANALYSIS_SCHEMA,
            },
        )
        payload = parse_model_json_response(response.text, "handwriting-analysis")
        payload["mode"] = "gemini"
        payload["errors"] = [normalize_error_item(item) for item in payload.get("errors", [])]
        return payload


def configure_genai_auth(credentials_file, location):
    if os.environ.get("GEMINI_API_KEY"):
        return {"mode": "api_key"}

    candidate_paths = []
    if credentials_file:
        candidate_paths.append(Path(credentials_file))
    else:
        candidate_paths.extend(
            [
                Path.cwd() / "key.json",
                Path.cwd() / "key3.json",
                Path.cwd() / "scripts" / "key.json",
                Path.cwd() / "scripts" / "key3.json",
            ]
        )

    credentials_path = next((path for path in candidate_paths if path.exists()), None)
    if not credentials_path:
        raise RuntimeError(
            "Keine Authentifizierung gefunden. Setze GEMINI_API_KEY oder lege eine Service-Account-Datei wie key.json ab."
        )

    payload = json.loads(credentials_path.read_text(encoding="utf-8"))
    project_id = payload.get("project_id")
    if not project_id:
        raise RuntimeError(f"In {credentials_path} fehlt project_id.")

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(credentials_path.resolve())
    os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
    os.environ["GOOGLE_CLOUD_LOCATION"] = location
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
    return {
        "mode": "vertex_ai_service_account",
        "project_id": project_id,
        "location": location,
        "credentials_file": str(credentials_path.resolve()),
    }


def parse_model_json_response(raw_text, label):
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

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    preview = (raw_text or "").strip().replace("\n", "\\n")[:500]
    raise RuntimeError(f"Gemini lieferte fuer '{label}' kein gueltiges JSON. Antwortanfang: {preview}")


def normalize_error_item(item):
    bbox = item.get("bbox", {})
    normalized_bbox = {
        "x": clamp_box_value(bbox.get("x")),
        "y": clamp_box_value(bbox.get("y")),
        "width": clamp_box_value(bbox.get("width"), minimum=20),
        "height": clamp_box_value(bbox.get("height"), minimum=20),
    }
    return {
        "written_word": str(item.get("written_word", "")).strip(),
        "correct_word": str(item.get("correct_word", "")).strip(),
        "lemma": str(item.get("lemma", "")).strip(),
        "general_tip": str(item.get("general_tip", "")).strip(),
        "category_hint": str(item.get("category_hint", "")).strip(),
        "bbox": normalized_bbox,
    }


def clamp_box_value(value, minimum=0):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = minimum
    return max(minimum, min(number, 1000))


def enrich_handwriting_analysis(raw_analysis, repository, search_service):
    enriched_errors = []
    for index, item in enumerate(raw_analysis.get("errors", []), start=1):
        lemma_candidate = item.get("lemma") or item.get("correct_word")
        match = None
        if lemma_candidate:
            resolved = search_service.resolve_query(lemma_candidate)
            match = resolved.get("match")

        word = repository.get_word_details(match["lemma"]) if match and match.get("lemma") else None
        spelling_categories = word.get("spelling_categories", []) if word else []
        strategy = word.get("spelling_strategy") if word else ""
        correct_word = item.get("correct_word") or (word.get("lemma") if word else "")
        display_category = spelling_categories[0] if spelling_categories else item.get("category_hint", "")
        general_tip = strategy or item.get("general_tip") or "Achte auf das Wort und höre genau hin."

        enriched_errors.append(
            {
                "id": f"error-{index}",
                "written_word": item.get("written_word", ""),
                "correct_word": correct_word,
                "word_lemma": word.get("lemma") if word else None,
                "lemma": word.get("lemma") if word else item.get("lemma", ""),
                "bbox": item.get("bbox", {}),
                "general_tip": general_tip,
                "category": display_category,
                "categories": spelling_categories,
                "strategy": strategy,
            }
        )

    return {
        "mode": raw_analysis.get("mode", "mock"),
        "recognized_text": raw_analysis.get("recognized_text", ""),
        "errors": enriched_errors,
    }


def build_handwriting_service(config):
    mode = config.get("HANDWRITING_MODE", "mock")
    if mode == "gemini":
        try:
            return GeminiHandwritingAnalysisService(
                model=config.get("HANDWRITING_GEMINI_MODEL", "gemini-2.5-flash"),
                credentials_file=config.get("GEMINI_CREDENTIALS_FILE"),
                location=config.get("GEMINI_LOCATION", "global"),
            )
        except Exception as exc:
            fallback = MockHandwritingAnalysisService()
            fallback.startup_warning = str(exc)
            fallback.requested_mode = "gemini"
            return fallback
    return MockHandwritingAnalysisService()
