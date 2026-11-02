"""Explicit, exclusive schema job: python -m grundschul_woerterbuch.migrate."""
import fcntl
import os
from pathlib import Path
from .db import init_db

database = Path(os.environ.get('DATABASE', 'data/grundschul_woerterbuch.sqlite3'))
database.parent.mkdir(parents=True, exist_ok=True)
with open(str(database) + '.migration.lock', 'a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    init_db(str(database))
