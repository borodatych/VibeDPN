"""AdGuard's query log as the per-device DNS journal of routing.mode smart.

The resolver of core does not know which device asked (AdGuard asks it from its own address);
AdGuard's log does. Records come newest first, with the time to the nanosecond
(docs/knowledge/adguard/domainUpstreams.md, fixture tests/fixtures/adguard_querylog_v0_107_79.json).
"""

from __future__ import annotations

from calendar import timegm
from collections.abc import Iterable
from dataclasses import dataclass
from time import strptime

from vibedpn.engine.learning import DnsEvent

QUERYLOG_PATH = "/control/querylog"
PAGE_LIMIT = 200


class QueryLogError(ValueError):
    """AdGuard answered something that is not its query log."""


@dataclass(frozen=True)
class LogRecord:
    """One record: the event plus what the sniffer shows."""

    event: DnsEvent
    stamp: str  # the time exactly as AdGuard wrote it, the cursor
    qtype: str
    cached: bool
    addresses: list[str]


def parse_time(stamp: str) -> float:
    """``2026-09-14T07:53:55.818445813Z`` → epoch seconds (to the microsecond)."""
    if not stamp.endswith("Z"):
        raise QueryLogError(f"{stamp!r} is not a UTC time")
    whole, _, fraction = stamp[:-1].partition(".")
    try:
        seconds = timegm(strptime(whole, "%Y-%m-%dT%H:%M:%S"))
        micros = int((fraction + "000000")[:6]) if fraction else 0
    except ValueError as exc:
        raise QueryLogError(f"{stamp!r} is not a time of the query log") from exc
    return seconds + micros / 1_000_000


def parse_page(body: object) -> list[LogRecord]:
    """Records of one page, newest first as AdGuard gives them."""
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        raise QueryLogError("the query log has no data list")
    records = []
    for item in data:
        if not isinstance(item, dict):
            continue
        question = item.get("question")
        if not isinstance(question, dict) or not isinstance(question.get("name"), str):
            continue
        stamp = str(item.get("time", ""))
        answers = item.get("answer") or []
        records.append(
            LogRecord(
                event=DnsEvent(str(item.get("client", "")), question["name"], parse_time(stamp)),
                stamp=stamp,
                qtype=str(question.get("type", "")),
                cached=bool(item.get("cached", False)),
                addresses=[
                    str(answer["value"])
                    for answer in answers
                    if isinstance(answer, dict) and answer.get("type") in ("A", "AAAA")
                ],
            )
        )
    return records


def newer_than(records: Iterable[LogRecord], last_stamp: str | None) -> list[LogRecord]:
    """Records after the last one handled, oldest first; ``None``: everything is new."""
    if last_stamp is None:
        fresh = list(records)
    else:
        last = parse_time(last_stamp)
        fresh = [record for record in records if record.event.time > last]
    return sorted(fresh, key=lambda record: record.event.time)
