"""Domain lists of routing.lists: config, editing config.yaml, parsing, the cache and the fetch."""

import os
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from vibedpn.bootstrap import render_config
from vibedpn.config import Config, DomainList, DomainVia, load_config, parse_yaml
from vibedpn.config_edit import ListNotFoundError, remove_domain_list, set_domain_list
from vibedpn.engine.domainlists import (
    MAX_LIST_BYTES,
    ListCache,
    ListError,
    http_fetch,
    parse_list,
    refresh_list,
)
from vibedpn.engine.router import rule_countries, used_uplinks

from .conftest import home_config

URL = "https://lists.example/blocked.txt"


def smart_home(lists: list[dict[str, Any]]) -> dict[str, Any]:
    raw = home_config()
    raw["routing"]["mode"] = "smart"
    raw["routing"]["lists"] = lists
    return raw


def test_a_list_takes_a_channel_and_its_country_gets_a_consumer() -> None:
    config = Config.model_validate(smart_home([{"url": URL, "via": "dpn", "country": "de"}]))
    assert config.routing is not None
    assert config.routing.lists == [DomainList(url=URL, via=DomainVia.DPN, country="DE")]
    assert rule_countries(config) == ["DE"]
    assert "dpn-de" in used_uplinks(config)


@pytest.mark.parametrize(
    ("lists", "message"),
    [
        ([{"url": "ftp://lists.example/a", "via": "dpn"}], "is not an http(s) URL"),
        ([{"url": URL, "via": "direct", "country": "DE"}], "a country is only chosen for via dpn"),
        ([{"url": URL, "via": "dpn"}, {"url": URL, "via": "direct"}], "names a URL twice"),
        (
            [{"url": URL, "via": "vps"}],
            f"routing: {URL} goes via vps but that uplink is not enabled",
        ),
    ],
)
def test_a_wrong_list_is_refused_with_its_reason(lists: list[dict[str, Any]], message: str) -> None:
    with pytest.raises(ValidationError, match=message.replace("(", r"\(").replace(")", r"\)")):
        Config.model_validate(smart_home(lists))


def test_lists_are_added_changed_and_removed_in_config_yaml(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(render_config(Config.model_validate(home_config())), encoding="utf-8")
    config, _ = set_domain_list(path, DomainList(url=URL, via=DomainVia.DPN))
    config, _ = set_domain_list(path, DomainList(url=URL, via=DomainVia.DPN, country="NL"))
    assert config.routing is not None and config.routing.lists == [
        DomainList(url=URL, via=DomainVia.DPN, country="NL")
    ]
    assert load_config(path).routing == config.routing
    config, _ = remove_domain_list(path, URL)
    assert config.routing is not None and config.routing.lists == []
    with pytest.raises(ListNotFoundError):
        remove_domain_list(path, URL)


def test_the_rendered_config_keeps_its_lists() -> None:
    config = Config.model_validate(smart_home([{"url": URL, "via": "dpn", "country": "DE"}]))
    assert Config.model_validate(parse_yaml(render_config(config))).routing == config.routing


def test_the_three_line_forms_are_read_and_the_rest_is_skipped() -> None:
    text = """# a comment
! an adblock comment
Example.org
0.0.0.0 ads.example.net tracker.example.net
127.0.0.1 localhost
127.0.0.1 localhost.localdomain
||cdn.example.com^
||example.com/path^
||*.wild.example^
@@||allowed.example^
/regexp/
example.org   # the same domain again
not_a_domain
single
"""
    assert parse_list(text).domains == [
        "example.org",
        "ads.example.net",
        "tracker.example.net",
        "cdn.example.com",
    ]


def test_the_cache_keeps_one_file_per_url_and_drops_gone_lists(tmp_path: Path) -> None:
    cache = ListCache(tmp_path / "lists")
    assert cache.load(URL) is None
    cache.save(URL, "example.org\n")
    cache.save("https://other.example/x", "other.org\n")
    loaded = cache.load(URL)
    assert loaded is not None and loaded[0] == "example.org\n"
    cache.prune([URL])
    assert cache.load("https://other.example/x") is None
    assert [path.name for path in (tmp_path / "lists").iterdir()] == [cache.path(URL).name]


def test_a_fresh_copy_is_used_without_fetching(tmp_path: Path) -> None:
    cache = ListCache(tmp_path)
    cache.save(URL, "example.org\n")
    fetched: list[str] = []

    def fetch(url: str) -> str:
        fetched.append(url)
        return "new.example\n"

    got, state = refresh_list(URL, cache, fetch)
    assert got.domains == ["example.org"] and fetched == [] and state.error == ""


def test_a_stale_copy_is_fetched_anew_and_saved(tmp_path: Path) -> None:
    cache = ListCache(tmp_path)
    cache.save(URL, "example.org\n")
    os.utime(cache.path(URL), (1_000.0, 1_000.0))
    got, state = refresh_list(URL, cache, lambda _url: "new.example\n", now=lambda: 200_000.0)
    assert got.domains == ["new.example"] and state.fetched_at == 200_000.0
    loaded = cache.load(URL)
    assert loaded is not None and loaded[0] == "new.example\n"


def test_a_failed_fetch_keeps_the_copy_and_says_why(tmp_path: Path) -> None:
    cache = ListCache(tmp_path)
    cache.save(URL, "example.org\n")
    os.utime(cache.path(URL), (1_000.0, 1_000.0))

    def down(url: str) -> str:
        raise ListError(f"{url}: HTTP 503")

    got, state = refresh_list(URL, cache, down, now=lambda: 200_000.0)
    assert got.domains == ["example.org"] and state.fetched_at == 1_000.0
    assert "HTTP 503; the last copy is in use" in state.error
    # a page without a domain or a network never replaces a good copy
    got, state = refresh_list(URL, cache, lambda _url: "<html>", now=lambda: 200_000.0)
    assert got.domains == ["example.org"] and "not a single domain or network" in state.error
    got, state = refresh_list("https://new.example/x", cache, down)
    assert got.empty() and state.fetched_at is None and "HTTP 503" in state.error


def test_the_fetch_wants_200_and_a_bounded_body() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/missing":
            return httpx.Response(404)
        if request.url.path == "/huge":
            return httpx.Response(200, content=b"a" * (MAX_LIST_BYTES + 1))
        return httpx.Response(200, content=b"example.org\n")

    fetch = http_fetch(httpx.Client(transport=httpx.MockTransport(answer)))
    assert fetch("https://lists.example/ok") == "example.org\n"
    with pytest.raises(ListError, match="HTTP 404"):
        fetch("https://lists.example/missing")
    with pytest.raises(ListError, match="larger than 16 MiB"):
        fetch("https://lists.example/huge")


def test_a_list_of_networks_names_networks_and_a_mixed_one_both() -> None:
    """antifilter publishes lists of networks, one a.b.c.d/nn a line: the slash makes a network"""
    text = """1.1.1.1/32
2.16.6.0/24
10.1.2.3/24
2.16.6.0/24
not.a.network/24
0.0.0.0 ads.example.net
192.0.2.7
2001:db8::/32
example.org
"""
    content = parse_list(text)
    assert [str(item) for item in content.networks] == ["1.1.1.1/32", "2.16.6.0/24", "10.1.2.0/24"]
    assert content.domains == ["ads.example.net", "example.org"]  # a bare address is no network


def test_a_list_with_networks_only_is_a_list(tmp_path: Path) -> None:
    got, state = refresh_list(URL, ListCache(tmp_path), lambda _url: "198.18.0.0/24\n")
    assert got.domains == [] and [str(item) for item in got.networks] == ["198.18.0.0/24"]
    assert (state.domains, state.networks, state.error) == (0, 1, "")
