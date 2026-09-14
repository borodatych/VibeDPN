"""What routing.mode smart learned: CDNs that follow a site, kept across restarts of core.

Owner rules live in config.yaml; learned names do not — they change on their own and there can
be many. SQLite next to the device store, one row per name, the schema version in user_version.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

LEARNED_FILE = "learned.db"
SCHEMA_VERSION = 1
DB_TIMEOUT_SECONDS = 5.0


class LearnedError(RuntimeError):
    """The store of learned names could not be read or written."""


class LearnedSource(StrEnum):
    TIME = "time"  # asked by a device right after its site
    CNAME = "cname"  # the site's name points to it


@dataclass(frozen=True)
class LearnedName:
    name: str
    parent: str
    source: LearnedSource
    first_seen: float
    last_seen: float
    hits: int


class LearnedStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            with closing(self._connect()) as db, db:
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version > SCHEMA_VERSION:
                    raise LearnedError(
                        f"{path} has schema version {version}, this VibeDPN knows {SCHEMA_VERSION}"
                    )
                db.execute(
                    "CREATE TABLE IF NOT EXISTS learned ("
                    " name TEXT PRIMARY KEY, parent TEXT NOT NULL, source TEXT NOT NULL,"
                    " first_seen REAL NOT NULL, last_seen REAL NOT NULL, hits INTEGER NOT NULL)"
                )
                db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        except sqlite3.Error as exc:
            raise LearnedError(f"cannot open {path}: {exc}") from exc

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=DB_TIMEOUT_SECONDS)

    def record(self, name: str, parent: str, source: LearnedSource, now: float) -> bool:
        """Store or refresh a learned name; ``True`` when it is new (or followed another site)."""
        try:
            with closing(self._connect()) as db, db:
                row = db.execute("SELECT parent FROM learned WHERE name = ?", (name,)).fetchone()
                if row is None or row[0] != parent:
                    db.execute(
                        "INSERT OR REPLACE INTO learned"
                        " (name, parent, source, first_seen, last_seen, hits)"
                        " VALUES (?, ?, ?, ?, ?, 1)",
                        (name, parent, source.value, now, now),
                    )
                    return True
                db.execute(
                    "UPDATE learned SET last_seen = ?, hits = hits + 1 WHERE name = ?", (now, name)
                )
                return False
        except sqlite3.Error as exc:
            raise LearnedError(f"cannot write {self.path}: {exc}") from exc

    def remove(self, name: str) -> bool:
        try:
            with closing(self._connect()) as db, db:
                return db.execute("DELETE FROM learned WHERE name = ?", (name,)).rowcount > 0
        except sqlite3.Error as exc:
            raise LearnedError(f"cannot write {self.path}: {exc}") from exc

    def names(self) -> list[LearnedName]:
        try:
            with closing(self._connect()) as db:
                rows = db.execute(
                    "SELECT name, parent, source, first_seen, last_seen, hits FROM learned"
                    " ORDER BY parent, name"
                ).fetchall()
        except sqlite3.Error as exc:
            raise LearnedError(f"cannot read {self.path}: {exc}") from exc
        return [
            LearnedName(name, parent, LearnedSource(source), first, last, hits)
            for name, parent, source, first, last, hits in rows
        ]
