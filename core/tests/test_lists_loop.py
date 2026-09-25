"""routing.lists at runtime: the resolver index, the background round, /lists and the CLI line."""

import asyncio
import contextlib
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from vibedpn.api.app import create_app
from vibedpn.api.lists import LIST_RETRY_SECONDS, ListsStatus, list_due, watch_lists
from vibedpn.api.models import DomainListView
from vibedpn.api.state import BoxState
from vibedpn.api.uplink import UplinkWatchers
from vibedpn.bootstrap import render_config
from vibedpn.cli import render_domain_list
from vibedpn.config import Config, load_config
from vibedpn.engine.domainlists import (
    LIST_REFRESH_SECONDS,
    Fetch,
    ListCache,
    ListError,
    ListState,
)
from vibedpn.engine.resolver import Resolver, RuleIndex
from vibedpn.engine.router import ExitPlan

from .conftest import home_config

URL = "https://lists.example/blocked.txt"
OTHER = "https://lists.example/other.txt"


def smart_config(
    lists: list[dict[str, Any]], domains: list[dict[str, Any]] | None = None
) -> Config:
    raw = home_config()
    raw["routing"]["mode"] = "smart"
    raw["routing"]["lists"] = lists
    raw["routing"]["domains"] = domains or []
    return Config.model_validate(raw)


def test_a_rule_wins_over_a_list_for_the_same_name() -> None:
    config = smart_config(
        [{"url": URL, "via": "dpn", "country": "DE"}],
        [{"domain": "bank.example", "via": "direct"}],
    )
    index = RuleIndex.from_config(config, {URL: ["video.example", "bank.example"]})
    assert index.match("cdn.video.example") == "smart_dpn_de"
    assert index.match("www.bank.example") == "smart_direct"
    assert RuleIndex.from_config(config).match("video.example") is None


def test_new_list_domains_reach_the_resolver_and_survive_a_reload() -> None:
    config = smart_config([{"url": URL, "via": "dpn"}])
    resolver = Resolver(RuleIndex.from_config(config), lambda q: q, lambda _s: None)
    resolver.set_lists(config, {URL: ["video.example"]})
    assert resolver.index.match("video.example") == "smart_dpn_any"
    # a router apply reloads from config.yaml: the domains of the lists stay
    resolver.reload(smart_config([{"url": URL, "via": "direct"}]))
    assert resolver.index.match("video.example") == "smart_direct"


def run_rounds(
    rounds: int,
    current: Callable[[], Config],
    resolver: Resolver,
    cache: ListCache,
    fetch: Fetch,
    status: ListsStatus,
    clock: Callable[[], float] = time.time,
) -> None:
    done = 0

    async def sleep(_seconds: float) -> None:
        nonlocal done
        done += 1
        if done == rounds:
            raise asyncio.CancelledError

    with contextlib.suppress(asyncio.CancelledError):
        asyncio.run(watch_lists(current, resolver, cache, fetch, status, sleep=sleep, clock=clock))


def test_the_round_fetches_a_list_and_drops_a_gone_one(tmp_path: Path) -> None:
    configs = [smart_config([{"url": URL, "via": "direct"}])]
    resolver = Resolver(RuleIndex.from_config(configs[0]), lambda q: q, lambda _s: None)
    status = ListsStatus()
    cache = ListCache(tmp_path)
    fetched: list[str] = []

    def fetch(url: str) -> str:
        fetched.append(url)
        return "video.example\n0.0.0.0 ads.example\n"

    run_rounds(
        1, current=lambda: configs[-1], resolver=resolver, cache=cache, fetch=fetch, status=status
    )
    assert fetched == [URL]
    assert resolver.lists == {URL: ["video.example", "ads.example"]}
    assert status.states[URL].domains == 2 and status.states[URL].error == ""
    assert cache.load(URL) is not None

    configs.append(smart_config([]))
    run_rounds(
        1, current=lambda: configs[-1], resolver=resolver, cache=cache, fetch=fetch, status=status
    )
    assert resolver.lists == {} and status.states == {}
    assert cache.load(URL) is None


def test_a_down_list_is_reported_and_not_asked_every_round(tmp_path: Path) -> None:
    config = smart_config([{"url": URL, "via": "direct"}])
    resolver = Resolver(RuleIndex.from_config(config), lambda q: q, lambda _s: None)
    status = ListsStatus()
    asked: list[str] = []

    def down(url: str) -> str:
        asked.append(url)
        raise ListError(f"{url}: HTTP 503")

    run_rounds(
        3,
        current=lambda: config,
        resolver=resolver,
        cache=ListCache(tmp_path),
        fetch=down,
        status=status,
        clock=lambda: 1_000.0,
    )
    assert asked == [URL]
    assert status.states[URL].fetched_at is None and "HTTP 503" in status.states[URL].error


def test_a_list_is_due_when_new_aged_or_its_retry_came() -> None:
    fresh = ListState(URL, 5, 1_000.0)
    failed = ListState(URL, 0, None, "HTTP 503")
    assert list_due(None, None, 0.0)
    assert not list_due(fresh, 1_000.0, 1_000.0 + LIST_REFRESH_SECONDS - 1)
    assert list_due(fresh, 1_000.0, 1_000.0 + LIST_REFRESH_SECONDS)
    assert not list_due(failed, 1_000.0, 1_000.0 + LIST_RETRY_SECONDS - 1)
    assert list_due(failed, 1_000.0, 1_000.0 + LIST_RETRY_SECONDS)


def test_lists_are_added_shown_and_removed_through_the_api(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    config = smart_config([])
    path.write_text(render_config(config), encoding="utf-8")
    state = BoxState(
        load_config(path), path, apply=lambda _config: [], watchers=UplinkWatchers(ExitPlan.of({}))
    )
    status = ListsStatus()
    client = TestClient(create_app(state.config, state=state, lists=status))

    added = client.put("/lists", json={"url": URL, "via": "dpn", "country": "nl"})
    assert added.status_code == 200 and added.json()["country"] == "NL"
    assert load_config(path).routing is not None
    status.states = {URL: ListState(URL, 42, 1_700_000_000.0)}
    assert client.get("/lists").json() == [
        {
            "url": URL,
            "via": "dpn",
            "country": "NL",
            "uplink": None,
            "domains": 42,
            "networks": 0,
            "fetched_at": 1_700_000_000.0,
            "error": "",
        }
    ]
    assert client.put("/lists", json={"url": "ftp://x", "via": "direct"}).status_code == 422
    assert client.delete("/lists", params={"url": URL}).status_code == 204
    assert client.delete("/lists", params={"url": URL}).status_code == 404
    assert client.get("/lists").json() == []


def test_the_cli_line_says_what_copy_is_in_use() -> None:
    fetching = DomainListView(
        url=URL,
        via="direct",
        country=None,
        uplink=None,
        domains=0,
        networks=0,
        fetched_at=None,
        error="",
    )
    assert render_domain_list(fetching) == f"{URL}  direct  (fetching)"
    down = fetching.model_copy(update={"error": f"{URL}: HTTP 503"})
    assert render_domain_list(down) == f"{URL}  direct  (no copy yet) — {URL}: HTTP 503"
    kept = DomainListView(
        url=OTHER,
        via="dpn",
        country="DE",
        uplink=None,
        domains=7,
        networks=0,
        fetched_at=0.0,
        error="",
    )
    assert render_domain_list(kept).startswith(f"{OTHER}  dpn DE  (7 domains, fetched ")
    exit_list = kept.model_copy(update={"via": "wg", "country": None, "uplink": "proton"})
    assert render_domain_list(exit_list).startswith(f"{OTHER}  wg proton  (7 domains, fetched ")
    networks = kept.model_copy(update={"domains": 0, "networks": 919})
    assert render_domain_list(networks).startswith(f"{OTHER}  dpn DE  (0 domains, 919 networks, ")


def test_the_round_carries_the_networks_of_a_list_to_their_set(tmp_path: Path) -> None:
    configs = [smart_config([{"url": URL, "via": "dpn"}])]
    scripts: list[str] = []
    resolver = Resolver(RuleIndex.from_config(configs[0]), lambda q: q, scripts.append)
    status = ListsStatus()

    def fetch(_url: str) -> str:
        return "198.18.0.0/24\n198.18.1.0/24\nvideo.example\n"

    run_rounds(1, lambda: configs[-1], resolver, ListCache(tmp_path), fetch, status)
    assert [str(item) for item in resolver.list_networks[URL]] == ["198.18.0.0/24", "198.18.1.0/24"]
    assert (status.states[URL].domains, status.states[URL].networks) == (1, 2)
    assert any(
        "add element inet vibedpn_router smart_dpn_any_lnet { 198.18.0.0/23 }" in s for s in scripts
    )
    configs.append(smart_config([]))  # the list is gone: its networks go with it
    run_rounds(1, lambda: configs[-1], resolver, ListCache(tmp_path), fetch, status)
    assert resolver.list_networks == {}
