"""Per-peer traffic of the VPS tunnel, accumulated so that a restart does not forget it.

``wg show`` counts from the moment the interface came up: restart the box and every peer is back at
zero. That is fine for "is the tunnel alive" and useless for "how much has this peer used this
month" — the question any sharing of access eventually asks (roadmap: sharing access from a VPS).

So core samples the counters and adds the *difference* to a total kept in SQLite. A counter smaller
than the one seen before means the interface restarted, and then everything it shows is new
traffic: that is the only reading that neither loses bytes nor invents them.

The totals are per peer and per day, because a day is the smallest grain every period is built
from — a month, a week, since the first of the month — and the largest that stays small: a year of
one peer is 365 rows.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

DB_FILE = "traffic.db"
SCHEMA_VERSION = 1
DB_TIMEOUT_SECONDS = 5.0
# Two years of days per peer: enough for any report the owner asks for, still nothing in size.
RETENTION_DAYS = 730


@dataclass(frozen=True)
class Sample:
    """The raw counters of one peer, as ``wg show`` reports them right now."""

    public_key: str
    rx_bytes: int
    tx_bytes: int


@dataclass(frozen=True)
class Total:
    """What one peer has used over the period asked for."""

    public_key: str
    rx_bytes: int
    tx_bytes: int

    @property
    def total_bytes(self) -> int:
        return self.rx_bytes + self.tx_bytes


def day_of(moment: float) -> str:
    """The day a sample belongs to, in UTC: the box may stand in another timezone than its owner,
    and a total that shifts with the clock is a total nobody can check."""
    return datetime.fromtimestamp(moment, UTC).strftime("%Y-%m-%d")


def advance(previous: Sample | None, current: Sample) -> tuple[int, int]:
    """How many bytes are new since ``previous``.

    Never seen before: everything the counter shows is new — the peer may have been running while
    core was not. Smaller than before: the interface restarted, and the counter starts from zero,
    so again everything it shows is new. Otherwise the difference.
    """
    if previous is None:
        return max(current.rx_bytes, 0), max(current.tx_bytes, 0)
    rx = (
        current.rx_bytes
        if current.rx_bytes < previous.rx_bytes
        else current.rx_bytes - previous.rx_bytes
    )
    tx = (
        current.tx_bytes
        if current.tx_bytes < previous.tx_bytes
        else current.tx_bytes - previous.tx_bytes
    )
    return max(rx, 0), max(tx, 0)


def connect(directory: Path) -> sqlite3.Connection:
    """Open the traffic database of ``directory``, creating it and its schema when needed."""
    directory.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(directory / DB_FILE, timeout=DB_TIMEOUT_SECONDS)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS daily (
            public_key TEXT NOT NULL,
            day        TEXT NOT NULL,
            rx_bytes   INTEGER NOT NULL DEFAULT 0,
            tx_bytes   INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (public_key, day)
        );
        CREATE TABLE IF NOT EXISTS seen (
            public_key TEXT PRIMARY KEY,
            rx_bytes   INTEGER NOT NULL,
            tx_bytes   INTEGER NOT NULL
        );
        """
    )
    connection.commit()
    return connection


def _previous(connection: sqlite3.Connection, key: str) -> Sample | None:
    row = connection.execute(
        "SELECT rx_bytes, tx_bytes FROM seen WHERE public_key = ?", (key,)
    ).fetchone()
    return None if row is None else Sample(key, int(row[0]), int(row[1]))


def record(connection: sqlite3.Connection, samples: list[Sample], moment: float) -> int:
    """Add what is new in ``samples`` to the totals of their day; returns the bytes added."""
    day = day_of(moment)
    added = 0
    with closing(connection.cursor()) as cursor:
        for sample in samples:
            rx, tx = advance(_previous(connection, sample.public_key), sample)
            added += rx + tx
            if rx or tx:
                cursor.execute(
                    """
                    INSERT INTO daily (public_key, day, rx_bytes, tx_bytes) VALUES (?, ?, ?, ?)
                    ON CONFLICT (public_key, day) DO UPDATE
                    SET rx_bytes = rx_bytes + excluded.rx_bytes,
                        tx_bytes = tx_bytes + excluded.tx_bytes
                    """,
                    (sample.public_key, day, rx, tx),
                )
            cursor.execute(
                """
                INSERT INTO seen (public_key, rx_bytes, tx_bytes) VALUES (?, ?, ?)
                ON CONFLICT (public_key) DO UPDATE
                SET rx_bytes = excluded.rx_bytes, tx_bytes = excluded.tx_bytes
                """,
                (sample.public_key, sample.rx_bytes, sample.tx_bytes),
            )
    connection.commit()
    return added


def totals(connection: sqlite3.Connection, since_day: str | None = None) -> list[Total]:
    """What every peer has used since ``since_day`` (its own day included), newest period first."""
    query = "SELECT public_key, SUM(rx_bytes), SUM(tx_bytes) FROM daily"
    parameters: tuple[str, ...] = ()
    if since_day is not None:
        query += " WHERE day >= ?"
        parameters = (since_day,)
    query += " GROUP BY public_key ORDER BY SUM(rx_bytes) + SUM(tx_bytes) DESC"
    return [
        Total(str(key), int(rx or 0), int(tx or 0))
        for key, rx, tx in connection.execute(query, parameters).fetchall()
    ]


def forget(connection: sqlite3.Connection, key: str) -> None:
    """Drop everything about a peer that is gone: its totals are of no use to anyone, and keeping
    them would tell the next owner of that name how much the previous one used."""
    connection.execute("DELETE FROM daily WHERE public_key = ?", (key,))
    connection.execute("DELETE FROM seen WHERE public_key = ?", (key,))
    connection.commit()


def prune(connection: sqlite3.Connection, moment: float, days: int = RETENTION_DAYS) -> int:
    """Drop days older than the retention; returns how many rows went."""
    oldest = day_of(moment - days * 24 * 3600)
    with closing(connection.cursor()) as cursor:
        cursor.execute("DELETE FROM daily WHERE day < ?", (oldest,))
        removed = cursor.rowcount
    connection.commit()
    return removed
