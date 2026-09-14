"""The store of learned CDNs: survives a reopen, refreshes, follows a new site, removes."""

import sqlite3
from pathlib import Path

import pytest

from vibedpn.engine.learned import (
    SCHEMA_VERSION,
    LearnedError,
    LearnedSource,
    LearnedStore,
)


def test_learned_names_survive_a_reopen_and_count_their_hits(tmp_path: Path) -> None:
    path = tmp_path / "learned.db"
    store = LearnedStore(path)
    assert store.record("strm.yandex.net", "kinopoisk.ru", LearnedSource.TIME, 100.0) is True
    assert store.record("strm.yandex.net", "kinopoisk.ru", LearnedSource.TIME, 150.0) is False
    assert store.record("edge.cdn.example", "netflix.com", LearnedSource.CNAME, 120.0) is True
    names = LearnedStore(path).names()
    assert [(item.name, item.parent, item.source, item.hits) for item in names] == [
        ("strm.yandex.net", "kinopoisk.ru", LearnedSource.TIME, 2),
        ("edge.cdn.example", "netflix.com", LearnedSource.CNAME, 1),
    ]
    assert (names[0].first_seen, names[0].last_seen) == (100.0, 150.0)


def test_a_name_that_follows_another_site_starts_over(tmp_path: Path) -> None:
    store = LearnedStore(tmp_path / "learned.db")
    store.record("cdn.example", "kinopoisk.ru", LearnedSource.TIME, 1.0)
    store.record("cdn.example", "kinopoisk.ru", LearnedSource.TIME, 2.0)
    assert store.record("cdn.example", "netflix.com", LearnedSource.TIME, 3.0) is True
    (item,) = store.names()
    assert (item.parent, item.hits, item.first_seen) == ("netflix.com", 1, 3.0)


def test_remove(tmp_path: Path) -> None:
    store = LearnedStore(tmp_path / "learned.db")
    store.record("cdn.example", "kinopoisk.ru", LearnedSource.TIME, 1.0)
    assert store.remove("cdn.example") is True
    assert store.remove("cdn.example") is False
    assert store.names() == []


def test_a_newer_schema_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "learned.db"
    with sqlite3.connect(path) as db:
        db.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    with pytest.raises(LearnedError, match="schema version"):
        LearnedStore(path)
