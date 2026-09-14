"""The smart loop of core: query log records into the journal, the learner, the resolver
and the store."""

import json
from pathlib import Path

from vibedpn.api.smart import DnsJournal, SmartLoop
from vibedpn.config import Config
from vibedpn.engine.learned import LearnedSource, LearnedStore
from vibedpn.engine.learning import Learned
from vibedpn.engine.resolver import Resolver, RuleIndex

from .conftest import client_config


def smart_config() -> Config:
    raw = client_config()
    raw["upstreams"]["dpn"] = {"enabled": True}
    raw["routing"]["mode"] = "smart"
    raw["routing"]["domains"] = [{"domain": "kinopoisk.ru", "via": "dpn"}]
    return Config.model_validate(raw)


def record(client: str, name: str, stamp: str, qtype: str = "A") -> dict[str, object]:
    return {
        "client": client,
        "time": stamp,
        "cached": False,
        "question": {"class": "IN", "name": name, "type": qtype},
        "answer": [{"type": "A", "value": "203.0.113.7", "ttl": 60}],
    }


class Log:
    def __init__(self) -> None:
        self.pages: list[list[dict[str, object]]] = []

    def push(self, *records: dict[str, object]) -> None:
        # AdGuard answers newest first; each round sees everything so far
        known = [item for page in self.pages for item in page]
        self.pages.append(list(reversed(list(records))) + known)

    def __call__(self, _older_than: str | None) -> object:
        return {"data": self.pages[-1], "oldest": ""}


def loop_for(tmp_path: Path, log: Log) -> tuple[SmartLoop, list[str]]:
    config = smart_config()
    fills: list[str] = []
    resolver = Resolver(RuleIndex.from_config(config), lambda q: q, fills.append)
    store = LearnedStore(tmp_path / "learned.db")
    loop = SmartLoop(lambda: config, resolver, store, DnsJournal(), log, clock=lambda: 42.0)
    return loop, fills


def test_a_cdn_after_its_site_is_learned_journaled_and_stored(tmp_path: Path) -> None:
    log = Log()
    loop, _fills = loop_for(tmp_path, log)
    loop.start()
    log.push(
        record("192.168.1.9", "www.kinopoisk.ru", "2026-09-14T08:00:00.100Z"),
        record("192.168.1.9", "strm.yandex.net", "2026-09-14T08:00:02.000Z"),
    )
    assert loop.round() == [Learned("strm.yandex.net", "kinopoisk.ru")]
    entries = loop.journal.entries("192.168.1.9")
    assert [(e.name, e.channel, e.learned_from) for e in entries] == [
        ("www.kinopoisk.ru", "smart_dpn_any", None),
        ("strm.yandex.net", "direct", "kinopoisk.ru"),  # asked before it was learned
    ]
    assert loop.resolver.index.match("strm.yandex.net") == "smart_dpn_any"
    (stored,) = loop.store.names()
    assert (stored.name, stored.parent, stored.source) == (
        "strm.yandex.net",
        "kinopoisk.ru",
        LearnedSource.TIME,
    )
    log.push(record("192.168.1.9", "strm.yandex.net", "2026-09-14T08:00:05.000Z"))
    assert loop.round() == []  # the cursor: old records are not seen twice
    assert [e.channel for e in loop.journal.entries("192.168.1.9")][-1] == "smart_dpn_any"


def test_what_was_learned_comes_back_after_a_restart_and_can_be_forgotten(tmp_path: Path) -> None:
    log = Log()
    first, _ = loop_for(tmp_path, log)
    first.store.record("strm.yandex.net", "kinopoisk.ru", LearnedSource.TIME, 1.0)
    second, _ = loop_for(tmp_path, log)
    second.start()
    assert second.resolver.index.match("strm.yandex.net") == "smart_dpn_any"
    assert second.forget("strm.yandex.net") is True
    assert second.resolver.index.match("strm.yandex.net") is None
    assert second.store.names() == []


def test_the_recorded_log_of_adguard_goes_into_the_journal(tmp_path: Path) -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "adguard_querylog_v0_107_79.json").read_text()
    )
    loop, _ = loop_for(tmp_path, lambda _older: fixture)  # type: ignore[arg-type]
    loop.round()
    assert loop.journal.clients() == ["127.0.0.21", "127.0.0.22"]
    assert len(loop.journal.entries("127.0.0.21")) == 3
