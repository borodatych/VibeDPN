"""The event journal of the box: what happened to its links, kept in SQLite (decision 24).

An event is data, never a phrase: a kind (``wifi``, ``uplink``), a subject (a MAC, an uplink key),
an action code and a few numbers. The panel and the CLI build the sentence, so the journal reads
in any language and no code ever branches on its text.

The journal keeps ``RETENTION_SECONDS`` of history and at most ``MAX_EVENTS`` rows; both are cut
on every write, so the file never grows without bound on a box nobody looks after.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

DB_FILE = "events.db"
SCHEMA_VERSION = 1
RETENTION_SECONDS = 30 * 24 * 3600
MAX_EVENTS = 50_000
DEFAULT_LIMIT = 500
DB_TIMEOUT_SECONDS = 5.0

Detail = dict[str, int | float | str]


class EventKind(StrEnum):
    WIFI = "wifi"
    UPLINK = "uplink"


class EventAction(StrEnum):
    # wifi: subject is the MAC of the client, or the interface for the access point itself
    CLIENT_CONNECTED = "client_connected"
    CLIENT_DISCONNECTED = "client_disconnected"  # detail: session_seconds when it is known
    AP_ENABLED = "ap_enabled"
    AP_DISABLED = "ap_disabled"
    # uplink: subject is the uplink key
    GATEWAY_ANSWERS = "gateway_answers"
    GATEWAY_SILENT = "gateway_silent"
    # the traffic of an uplink in use moved to or from a fallback uplink (decision 32); detail:
    # through — the uplink carrying it now, or direct / held when no uplink answers
    REROUTED = "rerouted"


class EventError(RuntimeError):
    """The journal could not be read or written."""


@dataclass(frozen=True)
class Event:
    time: float  # unix seconds
    kind: EventKind
    subject: str
    action: EventAction
    detail: Detail = field(default_factory=dict)


class EventStore:
    """Append-only rows, newest read first; old and surplus rows are dropped on every write."""

    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            with closing(self._connect()) as db, db:
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version > SCHEMA_VERSION:
                    raise EventError(
                        f"{path} has schema version {version}, this VibeDPN knows {SCHEMA_VERSION}"
                    )
                db.execute(
                    "CREATE TABLE IF NOT EXISTS events ("
                    " id INTEGER PRIMARY KEY AUTOINCREMENT, time REAL NOT NULL,"
                    " kind TEXT NOT NULL, subject TEXT NOT NULL, action TEXT NOT NULL,"
                    " detail TEXT NOT NULL)"
                )
                db.execute("CREATE INDEX IF NOT EXISTS events_time ON events (time)")
                db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        except sqlite3.Error as exc:
            raise EventError(f"cannot open {path}: {exc}") from exc

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=DB_TIMEOUT_SECONDS)

    def add(self, event: Event) -> None:
        try:
            with closing(self._connect()) as db, db:
                db.execute(
                    "INSERT INTO events (time, kind, subject, action, detail)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (
                        event.time,
                        event.kind.value,
                        event.subject,
                        event.action.value,
                        json.dumps(event.detail, sort_keys=True),
                    ),
                )
                db.execute("DELETE FROM events WHERE time < ?", (event.time - RETENTION_SECONDS,))
                db.execute(
                    "DELETE FROM events WHERE id <= (SELECT MAX(id) FROM events) - ?",
                    (MAX_EVENTS,),
                )
        except sqlite3.Error as exc:
            raise EventError(f"cannot write {self.path}: {exc}") from exc

    def events(
        self,
        *,
        kind: EventKind | None = None,
        since: float | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> list[Event]:
        """Newest first."""
        clauses: list[str] = []
        values: list[str | float] = []
        if kind is not None:
            clauses.append("kind = ?")
            values.append(kind.value)
        if since is not None:
            clauses.append("time >= ?")
            values.append(since)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        try:
            with closing(self._connect()) as db:
                rows = db.execute(
                    "SELECT time, kind, subject, action, detail FROM events"
                    f"{where} ORDER BY time DESC, id DESC LIMIT ?",
                    (*values, limit),
                ).fetchall()
        except sqlite3.Error as exc:
            raise EventError(f"cannot read {self.path}: {exc}") from exc
        return [
            Event(time, EventKind(kind_), subject, EventAction(action), json.loads(detail))
            for time, kind_, subject, action, detail in rows
        ]
