from __future__ import annotations
import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from .paths import DATA


class Conflict(ValueError):
    pass


class Store:
    def __init__(self, path=DATA / "studio.sqlite3"):
        self.path = path
        self.lock = threading.RLock()
        with self.connection() as db:
            db.executescript("""
              PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS records (
                kind TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL,
                updated REAL NOT NULL, PRIMARY KEY(kind,id));
              CREATE INDEX IF NOT EXISTS records_updated ON records(kind,updated DESC);
            """)

    @contextmanager
    def connection(self):
        with self.lock, sqlite3.connect(self.path, timeout=15) as db:
            db.row_factory = sqlite3.Row
            yield db

    def get(self, kind: str, ident: str):
        with self.connection() as db:
            row = db.execute(
                "SELECT data FROM records WHERE kind=? AND id=?", (kind, ident)
            ).fetchone()
        if not row:
            raise KeyError(ident)
        return json.loads(row["data"])

    def list(self, kind: str, limit: int = 200):
        with self.connection() as db:
            return [
                json.loads(row["data"])
                for row in db.execute(
                    "SELECT data FROM records WHERE kind=? ORDER BY updated DESC LIMIT ?",
                    (kind, limit),
                )
            ]

    def save(self, kind: str, value: dict, revision: int | None = None):
        value = dict(value)
        value.setdefault("id", uuid.uuid4().hex)
        with self.connection() as db:
            if revision is not None:
                row = db.execute(
                    "SELECT data FROM records WHERE kind=? AND id=?",
                    (kind, value["id"]),
                ).fetchone()
                if not row or json.loads(row["data"]).get("revision") != revision:
                    raise Conflict("内容已更新，请刷新后重试")
            value["updated_at"] = time.time()
            db.execute(
                "INSERT OR REPLACE INTO records VALUES (?,?,?,?)",
                (
                    kind,
                    value["id"],
                    json.dumps(value, ensure_ascii=False),
                    value["updated_at"],
                ),
            )
        return value

    def delete(self, kind: str, ident: str):
        with self.connection() as db:
            db.execute("DELETE FROM records WHERE kind=? AND id=?", (kind, ident))


store = Store()
