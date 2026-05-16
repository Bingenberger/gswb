import sqlite3


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lemma TEXT NOT NULL UNIQUE,
    normalized_lemma TEXT NOT NULL UNIQUE,
    part_of_speech TEXT NOT NULL,
    syllables TEXT,
    example_sentence TEXT,
    definition TEXT,
    spelling_strategy TEXT,
    image_filename TEXT,
    audio_filename TEXT
);

CREATE TABLE IF NOT EXISTS translations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id INTEGER NOT NULL,
    language_code TEXT NOT NULL,
    translation TEXT NOT NULL,
    FOREIGN KEY(word_id) REFERENCES words(id) ON DELETE CASCADE,
    UNIQUE(word_id, language_code)
);

CREATE TABLE IF NOT EXISTS spelling_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    FOREIGN KEY(word_id) REFERENCES words(id) ON DELETE CASCADE,
    UNIQUE(word_id, category)
);

CREATE TABLE IF NOT EXISTS word_family_bases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id INTEGER NOT NULL,
    family_base TEXT NOT NULL,
    normalized_family_base TEXT NOT NULL,
    FOREIGN KEY(word_id) REFERENCES words(id) ON DELETE CASCADE,
    UNIQUE(word_id, normalized_family_base)
);

CREATE TABLE IF NOT EXISTS relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_word_id INTEGER NOT NULL,
    target_word_id INTEGER NOT NULL,
    relation_type TEXT NOT NULL CHECK (relation_type IN ('word_family', 'word_field', 'synonym')),
    FOREIGN KEY(source_word_id) REFERENCES words(id) ON DELETE CASCADE,
    FOREIGN KEY(target_word_id) REFERENCES words(id) ON DELETE CASCADE,
    UNIQUE(source_word_id, target_word_id, relation_type)
);

CREATE TABLE IF NOT EXISTS misspellings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id INTEGER NOT NULL,
    variant TEXT NOT NULL,
    FOREIGN KEY(word_id) REFERENCES words(id) ON DELETE CASCADE,
    UNIQUE(word_id, variant)
);

CREATE TABLE IF NOT EXISTS noun_forms (
    word_id INTEGER PRIMARY KEY,
    article TEXT,
    singular_form TEXT,
    plural_form TEXT,
    FOREIGN KEY(word_id) REFERENCES words(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS verb_forms (
    word_id INTEGER PRIMARY KEY,
    infinitive TEXT,
    ich_form TEXT,
    du_form TEXT,
    er_sie_es_form TEXT,
    wir_form TEXT,
    ihr_form TEXT,
    sie_form TEXT,
    FOREIGN KEY(word_id) REFERENCES words(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS adjective_forms (
    word_id INTEGER PRIMARY KEY,
    positive_form TEXT,
    comparative_form TEXT,
    superlative_form TEXT,
    FOREIGN KEY(word_id) REFERENCES words(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_words_normalized_lemma ON words(normalized_lemma);
CREATE INDEX IF NOT EXISTS idx_misspellings_variant ON misspellings(variant);
CREATE INDEX IF NOT EXISTS idx_relations_source_type ON relations(source_word_id, relation_type);
CREATE INDEX IF NOT EXISTS idx_spelling_categories_word_id ON spelling_categories(word_id);
CREATE INDEX IF NOT EXISTS idx_word_family_bases_norm ON word_family_bases(normalized_family_base);
"""


def get_connection(database_path):
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def init_db(database_path):
    with get_connection(database_path) as connection:
        connection.executescript(SCHEMA)
        ensure_column(connection, "noun_forms", "nominativ_singular", "TEXT")
        ensure_column(connection, "noun_forms", "genitiv_singular", "TEXT")
        ensure_column(connection, "noun_forms", "dativ_singular", "TEXT")
        ensure_column(connection, "noun_forms", "akkusativ_singular", "TEXT")
        ensure_column(connection, "noun_forms", "nominativ_plural", "TEXT")
        ensure_column(connection, "noun_forms", "genitiv_plural", "TEXT")
        ensure_column(connection, "noun_forms", "dativ_plural", "TEXT")
        ensure_column(connection, "noun_forms", "akkusativ_plural", "TEXT")
        ensure_column(connection, "verb_forms", "perfekt_ich", "TEXT")
        ensure_column(connection, "verb_forms", "perfekt_du", "TEXT")
        ensure_column(connection, "verb_forms", "perfekt_er_sie_es", "TEXT")
        ensure_column(connection, "verb_forms", "perfekt_wir", "TEXT")
        ensure_column(connection, "verb_forms", "perfekt_ihr", "TEXT")
        ensure_column(connection, "verb_forms", "perfekt_sie", "TEXT")
        ensure_column(connection, "verb_forms", "praeteritum_ich", "TEXT")
        ensure_column(connection, "verb_forms", "praeteritum_du", "TEXT")
        ensure_column(connection, "verb_forms", "praeteritum_er_sie_es", "TEXT")
        ensure_column(connection, "verb_forms", "praeteritum_wir", "TEXT")
        ensure_column(connection, "verb_forms", "praeteritum_ihr", "TEXT")
        ensure_column(connection, "verb_forms", "praeteritum_sie", "TEXT")


def ensure_column(connection, table_name, column_name, column_type):
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    existing_columns = {row["name"] for row in rows}
    if column_name not in existing_columns:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
