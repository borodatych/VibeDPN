"""AdGuard's query log, as recorded from v0.107.79: records, time, cursor."""

import json
from pathlib import Path

import pytest

from vibedpn.engine.querylog import QueryLogError, newer_than, parse_page, parse_time

FIXTURE = Path(__file__).parent / "fixtures" / "adguard_querylog_v0_107_79.json"


def test_the_recorded_page_becomes_events_with_device_type_cache_and_addresses() -> None:
    records = parse_page(json.loads(FIXTURE.read_text(encoding="utf-8")))
    assert [(r.event.client, r.event.name, r.qtype, r.cached) for r in records] == [
        ("127.0.0.21", "www.example.com", "AAAA", False),
        ("127.0.0.21", "www.example.com", "A", True),
        ("127.0.0.22", "example.org", "A", False),
        ("127.0.0.21", "www.example.com", "A", False),
    ]
    assert records[0].addresses == []  # no answer section at all
    assert records[1].addresses == ["104.20.23.154", "172.66.147.243"]


def test_time_keeps_microseconds_of_the_nanosecond_stamp() -> None:
    assert parse_time("2026-09-14T07:53:55.818445813Z") == pytest.approx(1789372435.818446)
    assert parse_time("2026-09-14T07:53:55Z") == 1789372435.0
    with pytest.raises(QueryLogError):
        parse_time("yesterday")


def test_only_records_after_the_cursor_oldest_first() -> None:
    records = parse_page(json.loads(FIXTURE.read_text(encoding="utf-8")))
    everything = newer_than(records, None)
    assert [r.event.time for r in everything] == sorted(r.event.time for r in records)
    cursor = everything[1].stamp
    assert newer_than(records, cursor) == everything[2:]
    assert newer_than(records, everything[-1].stamp) == []


def test_a_foreign_body_is_refused() -> None:
    with pytest.raises(QueryLogError):
        parse_page({"oops": 1})
