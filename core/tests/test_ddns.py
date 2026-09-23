"""ddns: the update URL is a secret, the service is called when the address moves, and its words
decide success — some services fail with HTTP 200."""

import asyncio
import stat
from pathlib import Path

import httpx
import pytest

from vibedpn.config import Config
from vibedpn.engine.ddns import (
    REFRESH_SECONDS,
    URL_FILE,
    DdnsError,
    DdnsState,
    check_url,
    ddns_round,
    due,
    host_of,
    judge,
    load_state,
    save_url,
    watch_ddns,
)

from .conftest import home_config

TOKEN = "tok-3f9a1c7e"
URL = f"https://www.duckdns.org/update?domains=myhome&token={TOKEN}&ip={{ip}}"
NOW = 1_790_000_000.0


def config(*, enabled: bool = True) -> Config:
    return Config.model_validate({**home_config(), "ddns": {"enabled": enabled}})


class Internet:
    """ipify and the DDNS service, in one transport; records what the box asked."""

    def __init__(self, address: str = "203.0.113.5", answer: tuple[int, str] = (200, "OK")) -> None:
        self.address = address
        self.answer = answer
        self.updates: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.ipify.org":
            return httpx.Response(200, text=self.address)
        self.updates.append(str(request.url))
        status, text = self.answer
        return httpx.Response(status, text=text)


def client_of(internet: Internet) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(internet))


def with_url(tmp_path: Path) -> tuple[Path, Path]:
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    save_url(secrets, URL)
    return secrets, tmp_path / "ddns.json"


def test_the_url_is_https_only_and_kept_private(tmp_path: Path) -> None:
    with pytest.raises(DdnsError, match="https://"):
        check_url("http://www.duckdns.org/update?token=x")
    with pytest.raises(DdnsError):
        check_url("https://a.example/one two")
    save_url(tmp_path, URL + "\n")
    assert stat.S_IMODE((tmp_path / URL_FILE).stat().st_mode) == 0o600
    assert host_of(URL) == "www.duckdns.org"


@pytest.mark.parametrize(
    ("status", "body", "ok"),
    [
        (200, "OK", True),  # DuckDNS
        (200, "KO", False),  # DuckDNS says no with a 200
        (200, "good 203.0.113.5", True),  # dyndns2 (No-IP)
        (200, "nochg 203.0.113.5", True),
        (200, "badauth", False),
        (200, "nohost", False),
        (200, "!donator", False),  # an option the account does not have
        (200, "addresses updated", True),  # a service with its own words for success
        (500, "OK", False),
        (401, "", False),
    ],
)
def test_success_is_a_2xx_in_the_service_own_words(status: int, body: str, ok: bool) -> None:
    assert judge(status, body)[0] is ok


def test_a_call_is_due_on_a_new_address_and_once_a_day() -> None:
    told = DdnsState(told_ip="203.0.113.5", told_at=NOW)
    assert due(DdnsState(), "203.0.113.5", NOW)
    assert not due(told, "203.0.113.5", NOW + 60)
    assert due(told, "203.0.113.9", NOW + 60)
    assert due(told, "203.0.113.5", NOW + REFRESH_SECONDS)


def test_nothing_is_asked_while_ddns_is_off(tmp_path: Path) -> None:
    internet = Internet()
    secrets, state = with_url(tmp_path)
    assert ddns_round(config(enabled=False), secrets, state, client_of(internet), NOW) is None
    assert internet.updates == []


def test_the_service_is_called_only_when_the_address_moves(tmp_path: Path) -> None:
    internet = Internet()
    secrets, state_path = with_url(tmp_path)
    client = client_of(internet)
    first = ddns_round(config(), secrets, state_path, client, NOW)
    assert first is not None and first.last_ok and first.told_ip == "203.0.113.5"
    assert internet.updates == [URL.replace("{ip}", "203.0.113.5")]
    ddns_round(config(), secrets, state_path, client, NOW + 300)
    assert len(internet.updates) == 1  # same address: no call, nothing for No-IP to block
    internet.address = "198.51.100.7"
    moved = ddns_round(config(), secrets, state_path, client, NOW + 600)
    assert moved is not None and moved.told_ip == "198.51.100.7" and len(internet.updates) == 2


def test_a_refusal_keeps_the_old_address_so_the_next_round_tries_again(tmp_path: Path) -> None:
    internet = Internet(answer=(200, "KO"))
    secrets, state_path = with_url(tmp_path)
    client = client_of(internet)
    refused = ddns_round(config(), secrets, state_path, client, NOW)
    assert refused is not None and refused.last_ok is False and refused.told_ip is None
    assert refused.message == "200 KO"
    internet.answer = (200, "OK")
    accepted = ddns_round(config(), secrets, state_path, client, NOW + 300)
    assert accepted is not None and accepted.last_ok and accepted.told_ip == "203.0.113.5"


def test_a_failure_to_reach_the_service_never_quotes_the_token(tmp_path: Path) -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.ipify.org":
            return httpx.Response(200, text="203.0.113.5")
        raise httpx.ConnectError(f"cannot reach {request.url}", request=request)

    secrets, state_path = with_url(tmp_path)
    failed = ddns_round(
        config(), secrets, state_path, httpx.Client(transport=httpx.MockTransport(broken)), NOW
    )
    assert failed is not None and failed.last_ok is False
    assert failed.message == "www.duckdns.org: ConnectError"
    assert TOKEN not in state_path.read_text()


def test_a_failed_look_at_the_address_is_not_a_failed_call_and_clears_by_itself(
    tmp_path: Path,
) -> None:
    """The address is looked at every round, the service is called only when it moves: a look that
    failed once must not read as a failed call until the daily refresh."""
    internet = Internet()
    down = {"ipify": False}

    def flaky(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.ipify.org" and down["ipify"]:
            raise httpx.ConnectTimeout("no answer", request=request)
        return internet(request)

    secrets, state_path = with_url(tmp_path)
    client = httpx.Client(transport=httpx.MockTransport(flaky))
    ddns_round(config(), secrets, state_path, client, NOW)
    down["ipify"] = True
    blind = ddns_round(config(), secrets, state_path, client, NOW + 300)
    assert blind is not None and blind.address_error == "no public address: no answer"
    assert blind.last_ok is True and blind.told_ip == "203.0.113.5"  # the call still stands
    down["ipify"] = False
    seen = ddns_round(config(), secrets, state_path, client, NOW + 600)
    assert seen is not None and seen.address_error == "" and seen.last_ok is True
    assert len(internet.updates) == 1  # the address never moved: the service was asked once


def test_without_a_url_the_state_says_what_to_run(tmp_path: Path) -> None:
    (tmp_path / "secrets").mkdir()
    state = ddns_round(
        config(), tmp_path / "secrets", tmp_path / "ddns.json", client_of(Internet()), NOW
    )
    assert state is not None and "vibedpn ddns set" in state.message


def test_the_watcher_reads_the_live_config_and_keeps_going(tmp_path: Path) -> None:
    internet = Internet()
    secrets, state_path = with_url(tmp_path)
    configs = [config(), config(enabled=False), config()]
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    asyncio.run(
        watch_ddns(
            lambda: configs.pop(0),
            secrets,
            state_path,
            client=client_of(internet),
            sleep=sleep,
            now=lambda: NOW,
            rounds=3,
        )
    )
    assert len(slept) == 3 and len(internet.updates) == 1
    assert load_state(state_path).told_ip == "203.0.113.5"
