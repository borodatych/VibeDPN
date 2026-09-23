"""The Bot API as the box speaks it: the exit a device at home would take, the mark on the socket
before it connects, Telegram's answers, and a token that never leaks into a message."""

import json
import socket
import stat
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import IPv4Address
from pathlib import Path
from typing import Any, ClassVar

import pytest

from vibedpn.config import Config
from vibedpn.engine import telegram
from vibedpn.engine.router import exit_for
from vibedpn.engine.telegram import (
    Endpoint,
    Lookup,
    Route,
    TelegramError,
    TelegramSecrets,
    call,
    check_token,
    endpoint,
    load_secrets,
    marked_request,
    parse_updates,
    route_to,
    save_secrets,
    start_code,
)

from .conftest import home_config, vps_config

TOKEN = "123456:AAH-s3cr3t_t0ken-of-the-owner"
API = endpoint("https://api.telegram.org")
TELEGRAM_ADDRESS = IPv4Address("149.154.167.220")


def smart_box(mode: str = "smart", **routing: object) -> Config:
    raw: dict[str, Any] = home_config()
    raw["upstreams"] = {"dpn": {"enabled": True}, "tor": {"enabled": True}}
    raw["routing"] = {"mode": mode, "default_upstream": "dpn", **routing}
    return Config.model_validate(raw)


# --- the exit -----------------------------------------------------------------------------------


def test_the_exit_follows_the_mode_like_a_device_at_home() -> None:
    rules = {"domains": [{"domain": "telegram.org", "via": "tor"}]}
    full = smart_box("full", **rules)
    assert exit_for(full, "smart_tor", TELEGRAM_ADDRESS) == "dpn"  # full takes everything
    assert exit_for(smart_box("off", **rules), "smart_tor", TELEGRAM_ADDRESS) is None
    assert exit_for(Config.model_validate(vps_config()), None, TELEGRAM_ADDRESS) is None


def test_in_smart_a_network_rule_comes_before_the_rule_of_the_name() -> None:
    by_name = smart_box(domains=[{"domain": "telegram.org", "via": "tor"}])
    assert exit_for(by_name, "smart_tor", TELEGRAM_ADDRESS) == "tor"
    assert exit_for(by_name, None, TELEGRAM_ADDRESS) is None  # no rule: direct
    by_network = smart_box(
        domains=[{"domain": "telegram.org", "via": "tor"}],
        networks=[{"network": "149.154.160.0/20", "via": "dpn", "country": "DE"}],
    )
    assert exit_for(by_network, "smart_tor", TELEGRAM_ADDRESS) == "dpn-de"
    kept_direct = smart_box(
        networks=[
            {"network": "149.154.160.0/20", "via": "tor"},
            {"network": "149.154.167.0/24", "via": "direct"},
        ]
    )
    assert exit_for(kept_direct, None, TELEGRAM_ADDRESS) is None  # direct networks come first


def lookup(addresses: list[str], rule: str | None) -> Lookup:
    return Lookup(rule=lambda _name: rule, addresses=lambda _name: addresses)


def test_the_route_takes_the_address_the_resolver_gave_and_the_mark_of_its_exit() -> None:
    box = smart_box(domains=[{"domain": "telegram.org", "via": "tor"}])
    route = route_to(box, API, lookup([str(TELEGRAM_ADDRESS)], "smart_tor"))
    assert route == Route(address=str(TELEGRAM_ADDRESS), exit="tor", mark=0x60)
    stand = route_to(box, endpoint("http://198.18.0.9:8081/tg"), lookup([], None))
    assert stand == Route(address="198.18.0.9", exit=None, mark=None)  # no name, nothing asked


def test_a_name_without_an_address_is_an_error_with_the_reason() -> None:
    def refuse(_name: str) -> list[str]:
        raise OSError("Name or service not known")

    with pytest.raises(TelegramError, match=r"cannot resolve api\.telegram\.org"):
        route_to(smart_box(), API, Lookup(rule=lambda _name: None, addresses=refuse))
    with pytest.raises(TelegramError, match="no IPv4 address"):
        route_to(smart_box(), API, lookup([], None))


class RecordingSocket:
    """A socket that only records what is done to it, in order."""

    calls: ClassVar[list[tuple[object, ...]]] = []

    def __init__(self, family: int, kind: int) -> None:
        self.calls.append(("socket", family, kind))

    def setsockopt(self, level: int, option: int, value: int) -> None:
        self.calls.append(("setsockopt", level, option, value))

    def settimeout(self, timeout: float | None) -> None:
        self.calls.append(("settimeout", timeout))

    def connect(self, address: tuple[str, int]) -> None:
        self.calls.append(("connect", address))

    def close(self) -> None:
        self.calls.append(("close",))


def test_the_mark_is_on_the_socket_before_it_connects(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mark set after connect — where httpx sets its socket options — would send the
    handshake around the exit: the kill switch of the exit would not hold the bot."""
    RecordingSocket.calls = []
    monkeypatch.setattr(socket, "socket", RecordingSocket)
    monkeypatch.setattr(telegram, "SO_MARK", 36)
    telegram._marked_socket(Route("149.154.167.220", "tor", 0x60), 443, 20.0)
    assert [call_[0] for call_ in RecordingSocket.calls] == [
        "socket",
        "setsockopt",
        "settimeout",
        "connect",
    ]
    assert RecordingSocket.calls[0] == ("socket", socket.AF_INET, socket.SOCK_STREAM)
    assert RecordingSocket.calls[1] == ("setsockopt", socket.SOL_SOCKET, 36, 0x60)
    RecordingSocket.calls = []
    telegram._marked_socket(Route("149.154.167.220", None, None), 443, 20.0)
    assert "setsockopt" not in [call_[0] for call_ in RecordingSocket.calls]  # direct: no mark


def test_a_mark_the_system_cannot_set_is_refused_not_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    RecordingSocket.calls = []
    monkeypatch.setattr(socket, "socket", RecordingSocket)
    monkeypatch.setattr(telegram, "SO_MARK", None)
    with pytest.raises(OSError, match="cannot mark"):
        telegram._marked_socket(Route("149.154.167.220", "tor", 0x60), 443, 20.0)
    assert ("connect", ("149.154.167.220", 443)) not in RecordingSocket.calls
    assert RecordingSocket.calls[-1] == ("close",)


# --- calls and answers --------------------------------------------------------------------------


def answering(status: int, body: object) -> telegram.Transport:
    def transport(
        _where: Endpoint, _route: Route, _target: str, _body: bytes, _timeout: float
    ) -> tuple[int, bytes]:
        return status, json.dumps(body).encode()

    return transport


ROUTE = Route("149.154.167.220", "tor", 0x60)


def test_a_call_gives_the_result_or_telegram_s_own_words() -> None:
    ok = answering(200, {"ok": True, "result": {"username": "my_box_bot"}})
    assert call(API, ROUTE, TOKEN, "getMe", {}, transport=ok) == {"username": "my_box_bot"}
    unknown = answering(401, {"ok": False, "error_code": 401, "description": "Unauthorized"})
    with pytest.raises(TelegramError, match="Telegram: Unauthorized") as refused:
        call(API, ROUTE, TOKEN, "getMe", {}, transport=unknown)
    assert refused.value.rejected
    busy = answering(
        429,
        {
            "ok": False,
            "error_code": 429,
            "description": "Too Many Requests: retry after 7",
            "parameters": {"retry_after": 7},
        },
    )
    with pytest.raises(TelegramError) as paused:
        call(API, ROUTE, TOKEN, "sendMessage", {"chat_id": 1, "text": "x"}, transport=busy)
    assert paused.value.retry_after == 7.0 and not paused.value.rejected
    with pytest.raises(TelegramError, match="not an answer of the Bot API"):
        call(API, ROUTE, TOKEN, "getMe", {}, transport=answering(502, ["<html>"]))


def test_a_failure_on_the_way_names_its_class_and_never_the_token() -> None:
    def broken(
        _where: Endpoint, _route: Route, target: str, _body: bytes, _timeout: float
    ) -> tuple[int, bytes]:
        raise ConnectionRefusedError(f"cannot reach https://api.telegram.org{target}")

    with pytest.raises(TelegramError) as failed:
        call(API, ROUTE, TOKEN, "getMe", {}, transport=broken)
    assert str(failed.value) == "api.telegram.org (tor): ConnectionRefusedError"
    assert TOKEN not in str(failed.value)


class StandTelegram(BaseHTTPRequestHandler):
    """The stand-in a test stand points core at: it answers getMe and records the request."""

    seen: ClassVar[list[tuple[str, str, dict[str, Any]]]] = []

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.seen.append((self.path, self.headers["Host"], body))
        answer = json.dumps({"ok": True, "result": {"username": "stand_bot"}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(answer)))
        self.end_headers()
        self.wfile.write(answer)

    def log_message(self, *_args: object) -> None:
        return


def test_the_real_transport_speaks_the_bot_api_to_a_stand() -> None:
    StandTelegram.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), StandTelegram)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        where = endpoint(f"http://127.0.0.1:{port}/tg")
        route = Route("127.0.0.1", None, None)
        result = call(where, route, TOKEN, "getMe", {"x": 1}, transport=marked_request)
    finally:
        server.shutdown()
        server.server_close()
    assert result == {"username": "stand_bot"}
    assert StandTelegram.seen == [(f"/tg/bot{TOKEN}/getMe", f"127.0.0.1:{port}", {"x": 1})]


# --- linking a chat -----------------------------------------------------------------------------


def test_updates_carry_what_linking_a_chat_needs() -> None:
    result = [
        {
            "update_id": 7,
            "message": {
                "message_id": 1,
                "from": {"id": 42, "is_bot": False, "first_name": "Anna", "username": "anna"},
                "chat": {"id": 42, "type": "private", "first_name": "Anna", "username": "anna"},
                "text": "/start abc-DEF_123",
            },
        },
        {"update_id": 8, "edited_message": {"text": "x"}},
        {"update_id": 9, "message": {"chat": {"id": -5, "type": "group", "title": "Family"}}},
        {"no": "update"},
    ]
    updates = parse_updates(result)
    assert [(item.id, item.chat_id, item.chat_type, item.chat_name) for item in updates] == [
        (7, 42, "private", "@anna"),
        (8, None, "", ""),
        (9, -5, "group", "Family"),
    ]
    assert start_code(updates[0].text) == "abc-DEF_123"
    assert start_code("/start") is None and start_code("/help abc") is None
    assert parse_updates({"not": "a list"}) == []


def test_a_token_has_the_form_botfather_gives_and_is_kept_private(tmp_path: Path) -> None:
    assert check_token(f"  {TOKEN}\n") == TOKEN
    for wrong in ("", "no-colon", "123:abc def", "abc:def", "123:/../x"):
        with pytest.raises(TelegramError, match="bot's number"):
            check_token(wrong)
    save_secrets(tmp_path, TelegramSecrets(token=TOKEN, bot="my_box_bot", chat_id=42))
    assert stat.S_IMODE((tmp_path / "telegram.json").stat().st_mode) == 0o600
    kept = load_secrets(tmp_path)
    assert kept is not None and (kept.token, kept.chat_id) == (TOKEN, 42)
    assert load_secrets(tmp_path / "missing") is None
