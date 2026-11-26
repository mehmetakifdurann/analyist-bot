"""Transactional SQLite paper ledger. Commit wallet and events together."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class State:
    def __init__(self, path: Path, initial_cash: str):
        self.db = sqlite3.connect(path, timeout=5)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS wallet (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, kind TEXT NOT NULL, body TEXT NOT NULL);
        """)
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO wallet VALUES (1,?)",
                            (json.dumps(dict(cash=initial_cash, realized="0", pending=None, position=None,
                                             day=None, start_equity=None, locked=False, candle=-1)),))

    @contextmanager
    def transaction(self):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            previous = self.db.execute("SELECT body FROM wallet WHERE id=1").fetchone()[0]
            data = json.loads(previous)
            yield data
            encoded = json.dumps(data)
            if encoded != previous:
                self.db.execute("UPDATE wallet SET body=? WHERE id=1", (encoded,))

    def event(self, id_: str, kind: str, data: dict) -> None:
        self.db.execute("INSERT INTO events VALUES (?,?,?)", (id_,kind,json.dumps(data)))
