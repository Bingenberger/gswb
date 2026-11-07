"""Tests for /api/words and /api/word-filters (run: python -m unittest discover tests)."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from grundschul_woerterbuch import create_app
from grundschul_woerterbuch.db import init_db

WORDS = [
    # lemma, syllables, part of speech, categories, image exists, audio exists
    ("Lama", "La-ma", "Nomen", ["Mitsprechwort"], True, True),
    ("Mama", "Ma-ma", "Nomen", ["Mitsprechwort"], False, True),
    ("Banane", "Ba-na-ne", "Nomen", ["Mitsprechwort"], True, False),
    ("Auge", "Au-ge", "Nomen", ["Verlängerungswort"], True, True),
    ("laufen", "lau-fen", "Verb", ["Mitsprechwort"], False, False),
]


class ApiWordsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        db = base / "test.sqlite3"
        images, audio = base / "images", base / "audio"
        images.mkdir()
        audio.mkdir()
        init_db(str(db))
        connection = sqlite3.connect(db)
        for lemma, syllables, pos, categories, has_image, has_audio in WORDS:
            cursor = connection.execute(
                "INSERT INTO words (lemma, normalized_lemma, part_of_speech, syllables, image_filename, audio_filename)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (lemma, lemma.lower(), pos, syllables, f"{lemma}.webp", f"{lemma}.mp3"),
            )
            for category in categories:
                connection.execute("INSERT INTO spelling_categories (word_id, category) VALUES (?, ?)", (cursor.lastrowid, category))
            if has_image:
                (images / f"{lemma}.webp").write_bytes(b"x")
            if has_audio:
                (audio / f"{lemma}.mp3").write_bytes(b"x")
        connection.commit()
        connection.close()
        app = create_app({
            "TESTING": True, "SECRET_KEY": "x" * 40, "DATABASE": str(db), "IMPORT_DIR": str(base / "import"),
            "MEDIA_IMAGE_DIR": str(images), "MEDIA_AUDIO_DIR": str(audio), "HANDWRITING_UPLOAD_DIR": str(base / "uploads"),
            "HANDWRITING_MODE": "mock",
        })
        self.client = app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def lemmas(self, query):
        response = self.client.get("/api/words" + query)
        self.assertEqual(response.status_code, 200)
        return [w["lemma"] for w in response.get_json()["words"]]

    def test_known_letters(self):
        self.assertEqual(self.lemmas("?buchstaben=MAL"), ["Lama", "Mama"])

    def test_syllables_category_and_media(self):
        self.assertEqual(self.lemmas("?silben=3"), ["Banane"])
        self.assertEqual(self.lemmas("?kategorie=Mitsprechwort&mit_bild=1"), ["Banane", "Lama"])
        self.assertEqual(self.lemmas("?mit_ton=1&wortart=Nomen"), ["Auge", "Lama", "Mama"])
        self.assertEqual(self.lemmas("?enthaelt=au"), ["Auge", "laufen"])

    def test_payload_and_cors(self):
        response = self.client.get("/api/words?buchstaben=lam&anzahl=1")
        data = response.get_json()
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["words"][0], {
            "lemma": "Lama", "syllables": ["La", "ma"], "part_of_speech": "Nomen",
            "spelling_categories": ["Mitsprechwort"], "image": "/static/images/Lama.webp", "audio": "/static/audio/Lama.mp3",
        })
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "*")
        self.assertEqual(self.client.get("/api/words?buchstaben=mam").get_json()["words"][0]["image"], None)

    def test_invalid_numbers_are_ignored_and_limited(self):
        self.assertEqual(len(self.lemmas("?silben=abc&anzahl=99999")), 5)

    def test_filters(self):
        data = self.client.get("/api/word-filters").get_json()
        self.assertEqual(data["categories"][0], {"category": "Mitsprechwort", "count": 4})


if __name__ == "__main__":
    unittest.main()
