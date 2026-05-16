import datetime
import hashlib
from pathlib import Path

from .db import get_connection


class WordRepository:
    def __init__(self, database_path):
        self.database_path = database_path

    def _connect(self):
        return get_connection(self.database_path)

    def get_word_by_normalized_lemma(self, normalized_lemma):
        query = """
            SELECT * FROM words
            WHERE normalized_lemma = ?
        """
        with self._connect() as connection:
            row = connection.execute(query, (normalized_lemma,)).fetchone()
        return dict(row) if row else None

    def get_word_by_lemma(self, lemma):
        query = """
            SELECT * FROM words
            WHERE lemma = ?
        """
        with self._connect() as connection:
            row = connection.execute(query, (lemma,)).fetchone()
        return dict(row) if row else None

    def get_word_by_misspelling(self, normalized_variant):
        query = """
            SELECT w.*
            FROM misspellings m
            JOIN words w ON w.id = m.word_id
            WHERE m.variant = ?
        """
        with self._connect() as connection:
            row = connection.execute(query, (normalized_variant,)).fetchone()
        return dict(row) if row else None

    def get_word_details(self, lemma):
        word = self.get_word_by_lemma(lemma)
        if not word:
            return None

        word_id = word["id"]
        with self._connect() as connection:
            translations = connection.execute(
                """
                SELECT language_code, translation
                FROM translations
                WHERE word_id = ?
                ORDER BY language_code
                """,
                (word_id,),
            ).fetchall()

            spelling_categories = connection.execute(
                """
                SELECT category
                FROM spelling_categories
                WHERE word_id = ?
                ORDER BY category
                """,
                (word_id,),
            ).fetchall()

            relations = connection.execute(
                """
                SELECT r.relation_type, w.lemma
                FROM relations r
                JOIN words w ON w.id = r.target_word_id
                WHERE r.source_word_id = ?
                ORDER BY w.lemma
                """,
                (word_id,),
            ).fetchall()

            noun_forms = connection.execute(
                "SELECT * FROM noun_forms WHERE word_id = ?",
                (word_id,),
            ).fetchone()
            verb_forms = connection.execute(
                "SELECT * FROM verb_forms WHERE word_id = ?",
                (word_id,),
            ).fetchone()
            adjective_forms = connection.execute(
                "SELECT * FROM adjective_forms WHERE word_id = ?",
                (word_id,),
            ).fetchone()
            misspellings = connection.execute(
                """
                SELECT variant FROM misspellings
                WHERE word_id = ? AND variant != ?
                ORDER BY variant
                """,
                (word_id, word["normalized_lemma"]),
            ).fetchall()
            word_family_boxes = self._get_word_family_boxes(connection, word_id, word["lemma"])
            word_field_boxes = self._get_word_field_boxes(connection, word_id)

        word["translations"] = [dict(item) for item in translations]
        word["spelling_categories"] = [item["category"] for item in spelling_categories]
        word["relations"] = [dict(item) for item in relations]
        word["noun_forms"] = dict(noun_forms) if noun_forms else None
        word["verb_forms"] = dict(verb_forms) if verb_forms else None
        word["adjective_forms"] = dict(adjective_forms) if adjective_forms else None
        word["misspellings"] = [item["variant"] for item in misspellings]
        word["word_family_boxes"] = word_family_boxes
        word["word_field_boxes"] = word_field_boxes
        word["image_exists"] = self._media_exists("static/images", word.get("image_filename"))
        word["audio_exists"] = self._media_exists("static/audio", word.get("audio_filename"))
        return word

    def _get_word_family_boxes(self, connection, word_id, current_lemma):
        explicit_rows = connection.execute(
            """
            SELECT family_base, normalized_family_base
            FROM word_family_bases
            WHERE word_id = ?
            ORDER BY family_base
            """,
            (word_id,),
        ).fetchall()
        if explicit_rows:
            boxes = []
            for row in explicit_rows:
                related_rows = connection.execute(
                    """
                    SELECT DISTINCT w.lemma
                    FROM word_family_bases fb
                    JOIN words w ON w.id = fb.word_id
                    WHERE fb.normalized_family_base = ?
                      AND fb.word_id != ?
                    ORDER BY w.lemma
                    """,
                    (row["normalized_family_base"], word_id),
                ).fetchall()
                boxes.append(
                    {
                        "family_base": row["family_base"],
                        "related_words": [item["lemma"] for item in related_rows],
                    }
                )
            return boxes

        fallback_box = self._build_word_family_fallback_box(connection, word_id, current_lemma)
        return [fallback_box] if fallback_box else []

    def _build_word_family_fallback_box(self, connection, word_id, current_lemma):
        family_ids = {word_id}
        queue = [word_id]

        while queue:
            current_id = queue.pop(0)
            rows = connection.execute(
                """
                SELECT source_word_id, target_word_id
                FROM relations
                WHERE relation_type = 'word_family'
                  AND (source_word_id = ? OR target_word_id = ?)
                """,
                (current_id, current_id),
            ).fetchall()
            for row in rows:
                neighbor_id = row["target_word_id"] if row["source_word_id"] == current_id else row["source_word_id"]
                if neighbor_id not in family_ids:
                    family_ids.add(neighbor_id)
                    queue.append(neighbor_id)

        if len(family_ids) <= 1:
            return None

        placeholders = ",".join("?" for _ in family_ids)
        member_rows = connection.execute(
            f"""
            SELECT id, lemma
            FROM words
            WHERE id IN ({placeholders})
            ORDER BY lemma
            """,
            tuple(sorted(family_ids)),
        ).fetchall()

        member_lemmas = [row["lemma"] for row in member_rows]
        family_base, family_stem = self._choose_word_family_base(member_lemmas, current_lemma)
        related_words = [
            lemma
            for lemma in member_lemmas
            if lemma != current_lemma and family_stem in self._simplify_family_text(lemma)
        ]
        return {
            "family_base": family_base,
            "related_words": related_words,
        }

    def _get_word_field_boxes(self, connection, word_id):
        field_rows = connection.execute(
            """
            SELECT DISTINCT target_word_id, w.lemma AS field_lemma
            FROM relations r
            JOIN words w ON w.id = r.target_word_id
            WHERE r.source_word_id = ? AND r.relation_type = 'word_field'
            ORDER BY w.lemma
            """,
            (word_id,),
        ).fetchall()

        boxes = []
        for row in field_rows:
            related_rows = connection.execute(
                """
                SELECT DISTINCT w.lemma
                FROM relations r
                JOIN words w ON w.id = r.source_word_id
                WHERE r.target_word_id = ? AND r.relation_type = 'word_field' AND r.source_word_id != ?
                ORDER BY w.lemma
                """,
                (row["target_word_id"], word_id),
            ).fetchall()
            boxes.append(
                {
                    "field_lemma": row["field_lemma"],
                    "related_words": [item["lemma"] for item in related_rows],
                }
            )
        return boxes

    def _choose_word_family_base(self, member_lemmas, current_lemma):
        stem_to_lemmas = {}
        for lemma in member_lemmas:
            for stem in self._family_stem_candidates(lemma):
                stem_to_lemmas.setdefault(stem, set()).add(lemma)

        best_stem = None
        best_score = (-1, -1, "")
        for stem, lemmas in stem_to_lemmas.items():
            coverage = sum(
                1
                for lemma in member_lemmas
                if stem in self._simplify_family_text(lemma)
            )
            score = (coverage, len(stem), stem)
            if score > best_score and coverage >= 2:
                best_stem = stem
                best_score = score

        if best_stem:
            return best_stem.capitalize(), best_stem

        current_stem = self._simplify_family_text(current_lemma)
        return current_lemma, current_stem

    def _family_stem_candidates(self, lemma):
        text = self._simplify_family_text(lemma)
        if len(text) < 3:
            return [text]

        candidates = {text}
        for suffix in ("ern", "en", "er", "e", "n", "s"):
            if text.endswith(suffix) and len(text) - len(suffix) >= 3:
                candidates.add(text[: -len(suffix)])
        return sorted(candidates, key=len, reverse=True)

    def _simplify_family_text(self, text):
        replacements = str.maketrans(
            {
                "ä": "a",
                "ö": "o",
                "ü": "u",
                "Ä": "a",
                "Ö": "o",
                "Ü": "u",
                "ß": "s",
                " ": "",
                "-": "",
            }
        )
        simplified = text.translate(replacements).lower()
        return "".join(char for char in simplified if char.isalpha())

    def get_all_spelling_categories(self):
        query = """
            SELECT category, COUNT(*) as word_count
            FROM spelling_categories
            GROUP BY category
            ORDER BY word_count DESC, category
        """
        with self._connect() as connection:
            rows = connection.execute(query).fetchall()
        return [dict(row) for row in rows]

    def get_words_by_spelling_category(self, category):
        query = """
            SELECT w.lemma, w.part_of_speech
            FROM spelling_categories sc
            JOIN words w ON w.id = sc.word_id
            WHERE sc.category = ?
            ORDER BY w.lemma
        """
        with self._connect() as connection:
            rows = connection.execute(query, (category,)).fetchall()
        return [dict(row) for row in rows]

    def get_word_of_the_day(self):
        today = datetime.date.today().isoformat()
        seed = int(hashlib.md5(today.encode()).hexdigest(), 16)
        with self._connect() as connection:
            result = connection.execute("SELECT COUNT(*) as n FROM words").fetchone()
            count = result["n"]
            if not count:
                return None
            offset = seed % count
            row = connection.execute(
                "SELECT lemma FROM words ORDER BY lemma LIMIT 1 OFFSET ?",
                (offset,),
            ).fetchone()
        return dict(row) if row else None

    def _media_exists(self, relative_dir, filename):
        if not filename:
            return False
        base_dir = Path(self.database_path).parent.parent
        return (base_dir / relative_dir / filename).exists()

    def get_prefix_matches(self, normalized_prefix, limit=8):
        query = """
            SELECT lemma, part_of_speech
            FROM words
            WHERE normalized_lemma LIKE ?
            ORDER BY lemma
            LIMIT ?
        """
        with self._connect() as connection:
            rows = connection.execute(query, (f"{normalized_prefix}%", limit)).fetchall()
        return [dict(row) for row in rows]

    def get_misspelling_prefix_matches(self, normalized_prefix, limit=8):
        query = """
            SELECT DISTINCT w.lemma, w.part_of_speech
            FROM misspellings m
            JOIN words w ON w.id = m.word_id
            WHERE m.variant LIKE ?
            ORDER BY w.lemma
            LIMIT ?
        """
        with self._connect() as connection:
            rows = connection.execute(query, (f"{normalized_prefix}%", limit)).fetchall()
        return [dict(row) for row in rows]

    def get_search_terms(self):
        with self._connect() as connection:
            word_rows = connection.execute(
                "SELECT lemma, normalized_lemma, part_of_speech FROM words ORDER BY lemma"
            ).fetchall()
            misspelling_rows = connection.execute(
                """
                SELECT m.variant, w.lemma, w.part_of_speech
                FROM misspellings m
                JOIN words w ON w.id = m.word_id
                ORDER BY w.lemma
                """
            ).fetchall()

        return {
            "words": [dict(row) for row in word_rows],
            "misspellings": [dict(row) for row in misspelling_rows],
        }
