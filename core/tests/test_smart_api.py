"""The sniffer and learned names through core and the CLI."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from vibedpn import cli
from vibedpn.api import client as core_api
from vibedpn.api.app import create_app
from vibedpn.api.models import JournalEntryView, LearnedView
from vibedpn.api.smart import DnsJournal, JournalEntry, SmartLoop
from vibedpn.config import Config
from vibedpn.engine.learned import LearnedSource, LearnedStore
from vibedpn.engine.resolver import Resolver, RuleIndex

from .conftest import client_config
from .test_cli_routing import make_box

runner = CliRunner()


def smart_app(tmp_path: Path) -> tuple[TestClient, SmartLoop]:
    raw = client_config()
    raw["upstreams"]["dpn"] = {"enabled": True}
    raw["routing"]["domains"] = [{"domain": "kinopoisk.ru", "via": "dpn"}]
    config = Config.model_validate(raw)
    resolver = Resolver(RuleIndex.from_config(config), lambda q: q, lambda _s: None)
    loop = SmartLoop(
        lambda: config,
        resolver,
        LearnedStore(tmp_path / "learned.db"),
        DnsJournal(),
        lambda _older: {"data": []},
    )
    return TestClient(create_app(config, smart=loop)), loop


def test_journal_and_learned_names_through_the_api(tmp_path: Path) -> None:
    client, loop = smart_app(tmp_path)
    loop.journal.add(
        "192.168.1.9",
        JournalEntry(10.0, "www.kinopoisk.ru", "A", False, ["203.0.113.7"], "smart_dpn_any", None),
    )
    loop.journal.add(
        "192.168.1.9",
        JournalEntry(12.0, "strm.yandex.net", "A", True, [], "direct", "kinopoisk.ru"),
    )
    assert client.get("/dns/devices").json() == [{"client": "192.168.1.9", "queries": 2}]
    later = client.get("/dns/journal/192.168.1.9", params={"since": 10.0}).json()
    assert [entry["name"] for entry in later] == ["strm.yandex.net"]
    loop.store.record("strm.yandex.net", "kinopoisk.ru", LearnedSource.TIME, 12.0)
    loop.resolver.learn("strm.yandex.net", "kinopoisk.ru")
    assert [item["name"] for item in client.get("/learned").json()] == ["strm.yandex.net"]
    assert client.delete("/learned/strm.yandex.net").status_code == 204
    assert client.delete("/learned/strm.yandex.net").status_code == 404
    assert loop.resolver.index.match("strm.yandex.net") is None


def test_a_box_without_adguard_has_no_journal(tmp_path: Path) -> None:
    config = Config.model_validate(client_config())
    client = TestClient(create_app(config))
    assert client.get("/dns/devices").status_code == 404


def view(
    at: float, name: str, cached: bool, channel: str, learned_from: str | None
) -> JournalEntryView:
    return JournalEntryView(
        time=at,
        name=name,
        qtype="A",
        cached=cached,
        addresses=[],
        channel=channel,
        learned_from=learned_from,
    )


def test_dns_watch_and_learned_in_the_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_box(tmp_path, monkeypatch, client_config())
    entries = [
        JournalEntryView(
            time=10.0,
            name="www.kinopoisk.ru",
            qtype="A",
            cached=False,
            addresses=[],
            channel="smart_dpn_any",
            learned_from=None,
        ),
        JournalEntryView(
            time=12.0,
            name="strm.yandex.net",
            qtype="A",
            cached=True,
            addresses=[],
            channel="direct",
            learned_from="kinopoisk.ru",
        ),
    ]
    calls = [0]

    def journal(_port: int, client: str, since: float) -> list[JournalEntryView]:
        assert client == "192.168.1.9"
        calls[0] += 1
        if calls[0] > 1:
            raise KeyboardInterrupt
        return [entry for entry in entries if entry.time > since]

    monkeypatch.setattr(core_api, "journal", journal)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    watched = runner.invoke(cli.app, ["dns", "watch", "192.168.1.9", "--dir", str(tmp_path)])
    assert watched.exit_code == 0, watched.output
    assert "www.kinopoisk.ru  -> dpn_any" in watched.output
    assert "strm.yandex.net  -> direct cached  learned: follows kinopoisk.ru" in watched.output
    monkeypatch.setattr(
        core_api,
        "learned_names",
        lambda _port: [
            LearnedView(
                name="strm.yandex.net",
                parent="kinopoisk.ru",
                source="time",
                first_seen=1.0,
                last_seen=2.0,
                hits=3,
            )
        ],
    )
    learned = runner.invoke(cli.app, ["rule", "learned", "--dir", str(tmp_path)])
    assert "strm.yandex.net  follows kinopoisk.ru  (time, seen 3x)" in learned.output
