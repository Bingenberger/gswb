"""Word lists for reading tools (e.g. Blitzlesen and Silbenrutsche of the Grundschultafel).

Filters the dictionary by spelling category, part of speech, number of syllables,
letters the children already know, a contained letter group and the availability of
a picture or recording. Only media files that really exist are reported.
"""

import random
import time
import unicodedata
from pathlib import Path

from ..db import get_connection

MEDIA_CACHE_SECONDS = 300
MAX_LIMIT = 200


def _letters(text):
    """Lower-case letters of a word (umlauts and ß stay letters of their own)."""
    return {ch for ch in unicodedata.normalize("NFC", text.lower()) if ch.isalpha()}


class WordListService:
    def __init__(self, database_path, image_dir, audio_dir):
        self.database_path = database_path
        self.image_dir = Path(image_dir)
        self.audio_dir = Path(audio_dir)
        self._media = None
        self._media_loaded_at = 0.0

    # Existing media files, read once and refreshed every few minutes (thousands of files,
    # so checking each word on every request would be needlessly slow)
    def _existing_media(self):
        now = time.monotonic()
        if self._media is None or now - self._media_loaded_at > MEDIA_CACHE_SECONDS:
            def names(directory):
                try:
                    return {p.name for p in directory.iterdir() if p.is_file()}
                except OSError:
                    return set()
            self._media = (names(self.image_dir), names(self.audio_dir))
            self._media_loaded_at = now
        return self._media

    def _rows(self):
        query = """
            SELECT w.lemma, w.syllables, w.part_of_speech, w.image_filename, w.audio_filename,
                   GROUP_CONCAT(sc.category, '|') AS categories
            FROM words w
            LEFT JOIN spelling_categories sc ON sc.word_id = w.id
            GROUP BY w.id
            ORDER BY w.lemma COLLATE NOCASE
        """
        with get_connection(self.database_path) as connection:
            return [dict(row) for row in connection.execute(query).fetchall()]

    def categories(self):
        query = """
            SELECT category, COUNT(*) AS count FROM spelling_categories
            GROUP BY category ORDER BY count DESC, category
        """
        with get_connection(self.database_path) as connection:
            return [dict(row) for row in connection.execute(query).fetchall()]

    def parts_of_speech(self):
        query = "SELECT part_of_speech, COUNT(*) AS count FROM words GROUP BY part_of_speech ORDER BY count DESC"
        with get_connection(self.database_path) as connection:
            return [dict(row) for row in connection.execute(query).fetchall()]

    def find(self, *, categories=(), part_of_speech=None, syllables_min=None, syllables_max=None,
             letters=None, contains=None, max_length=None, with_image=False, with_audio=False,
             limit=20, shuffle=False):
        images, audios = self._existing_media()
        allowed = _letters(letters) if letters else None
        contains = contains.lower() if contains else None
        wanted_categories = set(categories)
        matches = []
        for row in self._rows():
            lemma = row["lemma"]
            parts = [p.strip() for p in (row["syllables"] or lemma).split("-") if p.strip()]
            row_categories = row["categories"].split("|") if row["categories"] else []
            image = row["image_filename"] if row["image_filename"] in images else None
            audio = row["audio_filename"] if row["audio_filename"] in audios else None
            if wanted_categories and not wanted_categories.intersection(row_categories):
                continue
            if part_of_speech and row["part_of_speech"] != part_of_speech:
                continue
            if syllables_min is not None and len(parts) < syllables_min:
                continue
            if syllables_max is not None and len(parts) > syllables_max:
                continue
            if allowed is not None and not _letters(lemma) <= allowed:
                continue
            if contains and contains not in lemma.lower():
                continue
            if max_length is not None and len(lemma) > max_length:
                continue
            if with_image and not image:
                continue
            if with_audio and not audio:
                continue
            matches.append({
                "lemma": lemma,
                "syllables": parts,
                "part_of_speech": row["part_of_speech"],
                "spelling_categories": row_categories,
                "image": f"/static/images/{image}" if image else None,
                "audio": f"/static/audio/{audio}" if audio else None,
            })
        total = len(matches)
        if shuffle:
            random.shuffle(matches)
        return {"total": total, "words": matches[: max(1, min(limit, MAX_LIMIT))]}
