import json
from pathlib import Path


REVIEW_KEY = "_review"


class JsonReviewService:
    def __init__(self, import_dir):
        self.import_dir = Path(import_dir)

    def list_entries(self):
        entries = []
        for file_path in sorted(self.import_dir.glob("*.json")):
            payload = self._read_json(file_path)
            review = self._review_data(payload)
            entries.append(
                {
                    "slug": file_path.stem,
                    "filename": file_path.name,
                    "lemma": payload.get("lemma", file_path.stem),
                    "wortart": payload.get("wortart", ""),
                    "approved": review["approved"],
                    "needs_regeneration": review["needs_regeneration"],
                }
            )
        return entries

    def get_entry(self, slug):
        file_path = self._path_for_slug(slug)
        if not file_path.exists():
            return None

        payload = self._read_json(file_path)
        entries = self.list_entries()
        current_index = next((index for index, item in enumerate(entries) if item["slug"] == slug), None)

        return {
            "slug": slug,
            "filename": file_path.name,
            "payload": payload,
            "raw_json": json.dumps(payload, ensure_ascii=False, indent=2),
            "relations_json": json.dumps(payload.get("beziehungen", []), ensure_ascii=False, indent=2),
            "grammar_json": json.dumps(payload.get("grammatische_formen", {}), ensure_ascii=False, indent=2),
            "review": self._review_data(payload),
            "entries": entries,
            "current_index": current_index,
            "prev_slug": entries[current_index - 1]["slug"] if current_index not in (None, 0) else None,
            "next_slug": entries[current_index + 1]["slug"] if current_index is not None and current_index + 1 < len(entries) else None,
        }

    def next_pending_slug(self):
        for entry in self.list_entries():
            if not entry["approved"] or entry["needs_regeneration"]:
                return entry["slug"]
        entries = self.list_entries()
        return entries[0]["slug"] if entries else None

    def update_flags(self, slug, *, approved=None, needs_regeneration=None):
        payload = self._load_payload(slug)
        review = self._review_data(payload)
        if approved is not None:
            review["approved"] = bool(approved)
        if needs_regeneration is not None:
            review["needs_regeneration"] = bool(needs_regeneration)
            if review["needs_regeneration"]:
                review["approved"] = False
        payload[REVIEW_KEY] = review
        self._write_payload(slug, payload)
        return payload

    def save_payload(self, slug, raw_json):
        payload = json.loads(raw_json)
        existing = self._load_payload(slug)
        if REVIEW_KEY in existing and REVIEW_KEY not in payload:
            payload[REVIEW_KEY] = existing[REVIEW_KEY]
        self._write_payload(slug, payload)
        return payload

    def _path_for_slug(self, slug):
        return self.import_dir / f"{slug}.json"

    def _load_payload(self, slug):
        file_path = self._path_for_slug(slug)
        if not file_path.exists():
            raise FileNotFoundError(slug)
        return self._read_json(file_path)

    def _read_json(self, file_path):
        return json.loads(Path(file_path).read_text(encoding="utf-8"))

    def _write_payload(self, slug, payload):
        self._path_for_slug(slug).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _review_data(self, payload):
        review = payload.get(REVIEW_KEY, {})
        return {
            "approved": bool(review.get("approved", False)),
            "needs_regeneration": bool(review.get("needs_regeneration", False)),
        }
