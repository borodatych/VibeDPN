"""The Telegram bot of core on a Telegram of its own: a token checked and kept, a chat linked by
its /start, an outage told through the exit and kept while Telegram is out of reach, the report at
its moment, the API that never gives the token back, the CLI and doctor."""

import asyncio
import json
import stat
from collections import deque
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from vibedpn import cli
from vibedpn.api import client as core_api
from vibedpn.api.app import create_app
from vibedpn.api.models import TelegramReportView, TelegramView
from vibedpn.api.state import BoxState
from vibedpn.api.telegram import LINK_SECONDS, TelegramBot
from vibedpn.bootstrap import render_config
from vibedpn.config import Config, Weekday, load_config
from vibedpn.doctor import TelegramFacts, Verdict, _telegram_result
from vibedpn.engine.events import Event, EventAction, EventKind
from vibedpn.engine.i18n import base_catalog
from vibedpn.engine.myst import Identity, ProviderStats, SessionTotals, Tokens
from vibedpn.engine.notices import STATE_FILE, BotState, Delivery
from vibedpn.engine.telegram import (
    Endpoint,
    Lookup,
    Route,
    TelegramError,
    TelegramSecrets,
    endpoint,
    load_secrets,
    save_secrets,
)

from .conftest import home_config

TOKEN = "123456:AAH-s3cr3t_t0ken-of-the-owner"
OTHER = "654321:AAH-an0ther_t0ken"
CHAT = 42
TELEGRAM_ADDRESS = "149.154.167.220"
MOSCOW = ZoneInfo("Europe/Moscow")
START = datetime(2026, 9, 21, 9, 59, 0, tzinfo=MOSCOW).timestamp()  # a Monday
WEI = 10**18
runner = CliRunner()


class FakeTelegram:
    """The Bot API of one bot, in memory: getMe, getUpdates, sendMessage."""

    def __init__(self, token: str = TOKEN) -> None:
        self.token = token
        self.updates: list[dict[str, Any]] = []
        self.sent: list[tuple[int, str]] = []
        self.routes: list[Route] = []
        self.unreachable = False
        self.on_poll: Callable[[], None] | None = None

    def __call__(
        self, _where: Endpoint, route: Route, target: str, body: bytes, _timeout: float
    ) -> tuple[int, bytes]:
        self.routes.append(route)
        if self.unreachable:
            raise ConnectionRefusedError("no route to host")
        _root, bot, method = target.rsplit("/", 2)
        if bot != f"bot{self.token}":
            refused = {"ok": False, "error_code": 401, "description": "Unauthorized"}
            return 401, json.dumps(refused).encode()
        payload = json.loads(body)
        result: object
        if method == "getMe":
            result = {"id": 7, "is_bot": True, "first_name": "Box", "username": "my_box_bot"}
        elif method == "getUpdates":
            if self.on_poll is not None:
                self.on_poll()
            offset = payload.get("offset", 0)
            result = [item for item in self.updates if item["update_id"] >= offset]
        else:
            self.sent.append((payload["chat_id"], payload["text"]))
            result = {"message_id": len(self.sent)}
        return 200, json.dumps({"ok": True, "result": result}).encode()


class Clock:
    def __init__(self, now: float = START) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class StopLoopError(Exception):
    """Ends the endless loop of the bot in a test."""


class Ticks:
    """The sleep of the loop: moves the clock, and stops the loop after so many ticks."""

    def __init__(self, clock: Clock, count: int) -> None:
        self.clock = clock
        self.count = count

    async def __call__(self, seconds: float) -> None:
        self.clock.now += seconds
        self.count -= 1
        if self.count <= 0:
            raise StopLoopError


def smart_home(**telegram: object) -> Config:
    raw: dict[str, Any] = home_config()
    raw["upstreams"] = {"dpn": {"enabled": True}, "tor": {"enabled": True}}
    raw["routing"] = {
        "mode": "smart",
        "default_upstream": "dpn",
        "domains": [{"domain": "telegram.org", "via": "tor"}],
    }
    raw["telegram"] = {"enabled": True, **telegram}
    return Config.model_validate(raw)


# What the resolver of the box answers: telegram.org is under the rule that sends it through tor.
LOOKUP = Lookup(
    rule=lambda name: "smart_tor" if name.endswith("telegram.org") else None,
    addresses=lambda _name: [TELEGRAM_ADDRESS],
)


def stats_of(total_myst: float) -> Callable[[], ProviderStats]:
    """The node of the box with this much earned in all."""

    def stats() -> ProviderStats:
        return ProviderStats(
            node_version="1.39.5",
            node_uptime="1h",
            monitoring_status="success",
            identity=Identity(
                id="0x1",
                registration_status="Registered",
                earnings_total_tokens=Tokens(wei=str(int(total_myst * WEI)), human=""),
            ),
            services=[],
            sessions=SessionTotals(),
        )

    return stats


class Box:
    """A bot in a temporary box directory, with its Telegram, clock and inbox."""

    def __init__(
        self,
        tmp_path: Path,
        config: Config,
        *,
        linked: bool = False,
        state: BotState | None = None,
        stats: Callable[[], ProviderStats] | None = None,
    ) -> None:
        self.config = config
        self.secrets = tmp_path / "secrets"
        self.data = tmp_path / "data"
        self.secrets.mkdir(mode=0o700, exist_ok=True)
        self.data.mkdir(exist_ok=True)
        if linked:
            save_secrets(
                self.secrets,
                TelegramSecrets(
                    token=TOKEN, bot="my_box_bot", chat_id=CHAT, chat_name="@anna", linked_at=1.0
                ),
            )
        if state is not None:
            (self.data / STATE_FILE).write_text(state.model_dump_json(), encoding="utf-8")
        self.telegram = FakeTelegram()
        self.clock = Clock()
        self.inbox: deque[Event] = deque()
        self.ticks = Ticks(self.clock, 0)
        self.bot = TelegramBot(
            lambda: self.config,
            secrets_dir=self.secrets,
            data_dir=self.data,
            catalog=base_catalog(),
            lookup=LOOKUP,
            inbox=self.inbox,
            stats=stats or stats_of(1.0),
            where=endpoint("https://api.telegram.org"),
            transport=self.telegram,
            clock=self.clock,
            sleep=self.ticks,
        )

    def run(self, ticks: int) -> None:
        self.ticks.count = ticks
        with pytest.raises(StopLoopError):
            asyncio.run(self.bot.run())

    def texts(self) -> list[str]:
        return [text for _chat, text in self.telegram.sent]


def update(number: int, chat_type: str, chat_id: int, text: str) -> dict[str, Any]:
    chat = {"id": chat_id, "type": chat_type, "first_name": "Anna", "username": "anna"}
    return {"update_id": number, "message": {"message_id": number, "chat": chat, "text": text}}


# --- the token and the chat ---------------------------------------------------------------------


def test_a_token_is_checked_through_the_exit_of_telegram_and_kept_private(tmp_path: Path) -> None:
    box = Box(tmp_path, smart_home())
    offer = box.bot.set_token(TOKEN)
    assert box.telegram.routes == [Route(TELEGRAM_ADDRESS, "tor", 0x60)]  # the rule of the box
    kept = load_secrets(box.secrets)
    assert kept is not None and (kept.token, kept.bot, kept.chat_id) == (TOKEN, "my_box_bot", None)
    assert stat.S_IMODE((box.secrets / "telegram.json").stat().st_mode) == 0o600
    status = box.bot.status()
    assert status.token_set and not status.linked and status.offer == offer
    box.telegram.token = OTHER  # Telegram knows only another token now
    with pytest.raises(TelegramError) as refused:
        box.bot.set_token(TOKEN)
    assert refused.value.rejected
    assert load_secrets(box.secrets) == kept


def test_the_start_with_the_code_links_the_private_chat_and_nothing_else_does(
    tmp_path: Path,
) -> None:
    box = Box(tmp_path, smart_home())
    offer = box.bot.set_token(TOKEN)
    box.telegram.updates = [
        update(1, "group", -5, f"/start {offer.code}"),
        update(2, "private", 99, "/start not-the-code"),
        update(3, "private", CHAT, f"/start {offer.code}"),
    ]
    asyncio.run(box.bot._listen())
    status = box.bot.status()
    assert status.linked and status.chat == "@anna" and status.linked_at == box.clock.now
    assert status.offer is None and status.waiting == 1  # the chat is told it is linked
    kept = load_secrets(box.secrets)
    assert kept is not None and kept.chat_id == CHAT


def test_a_link_nobody_opens_expires(tmp_path: Path) -> None:
    box = Box(tmp_path, smart_home())
    offer = box.bot.set_token(TOKEN)
    box.telegram.updates = [update(1, "private", 99, "/start not-the-code")]

    def later() -> None:
        box.clock.now += LINK_SECONDS

    box.telegram.on_poll = later
    asyncio.run(box.bot._listen())
    status = box.bot.status()
    assert not status.linked and status.offer is None and offer.code
    # the same token again keeps nothing it had not: still no chat, a fresh link
    assert box.bot.set_token(TOKEN).code != offer.code


# --- the loop -----------------------------------------------------------------------------------


def silent(key: str, at: float, *, alive: bool = False) -> Event:
    action = EventAction.GATEWAY_ANSWERS if alive else EventAction.GATEWAY_SILENT
    return Event(at, EventKind.UPLINK, key, action)


def test_a_long_outage_reaches_the_chat_through_the_exit_and_waits_while_it_cannot(
    tmp_path: Path,
) -> None:
    box = Box(tmp_path, smart_home(), linked=True)
    box.inbox.append(silent("dpn", box.clock.now))
    box.run(75)  # the threshold, the merge window, and a little more
    assert box.texts() == ["Exit dpn has not answered since 09:59."]
    assert box.telegram.routes[-1] == Route(TELEGRAM_ADDRESS, "tor", 0x60)
    assert box.telegram.sent[0][0] == CHAT
    # Telegram out of reach: the news waits, and says why
    box.telegram.unreachable = True
    box.inbox.append(silent("dpn", box.clock.now, alive=True))
    box.run(20)
    status = box.bot.status()
    assert status.waiting == 1 and status.delivery.last_ok is False
    assert status.delivery.message == "api.telegram.org via tor: ConnectionRefusedError"
    assert status.delivery.via == "via tor"
    box.telegram.unreachable = False
    box.run(60)  # past the pauses between attempts
    assert box.texts()[-1] == "Exit dpn answers again after 1 min 15 s of silence."
    assert box.bot.status().waiting == 0
    kept = json.loads((box.data / STATE_FILE).read_text(encoding="utf-8"))
    assert kept["outbox"] == [] and kept["downtime"] == {"dpn": 75.0}
    assert TOKEN not in (box.data / STATE_FILE).read_text(encoding="utf-8")


def test_nothing_is_kept_or_told_while_the_bot_is_off(tmp_path: Path) -> None:
    box = Box(tmp_path, smart_home(enabled=False), linked=True)
    box.inbox.append(silent("dpn", box.clock.now))
    box.run(90)
    assert box.telegram.sent == [] and not (box.data / STATE_FILE).exists()
    box.config = smart_home()  # turned on in the panel: no restart, no backlog
    box.run(5)
    assert box.telegram.sent == [] and (box.data / STATE_FILE).exists()


def test_the_weekly_report_comes_once_at_its_moment(tmp_path: Path) -> None:
    last_monday = datetime(2026, 9, 14, 10, 0, tzinfo=MOSCOW).timestamp()
    state = BotState(
        heartbeat=START, reported_slot=last_monday, period_since=last_monday, earnings_wei=str(WEI)
    )
    box = Box(tmp_path, smart_home(), linked=True, state=state, stats=stats_of(3.5))
    box.run(120)  # 09:59 → 10:01
    assert box.texts() == [
        "VibeDPN weekly report, 2026-09-14 to 2026-09-21\n"
        "Node: 2.5 MYST earned in these days, 3.5 MYST in all.\n"
        "Exits: no outages."
    ]
    box.run(120)
    assert len(box.texts()) == 1


def test_a_box_that_was_off_says_so_when_it_is_back(tmp_path: Path) -> None:
    box = Box(tmp_path, smart_home(), linked=True, state=BotState(heartbeat=START - 3600))
    box.run(15)
    assert box.texts() == ["The box is back: it was off for 1 h, 08:59 to 09:59."]


# --- the API ------------------------------------------------------------------------------------


class Api:
    """The core API of a box on disk, with the bot and a router that counts its applies."""

    def __init__(self, tmp_path: Path, config: Config, *, linked: bool = False) -> None:
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.path = tmp_path / "config.yaml"
        self.path.write_text(render_config(config), encoding="utf-8")
        self.box = Box(tmp_path, config, linked=linked)
        self.applied: list[Config] = []
        self.state = BoxState(config, self.path, apply=self._apply)
        self.box.bot._current = lambda: self.state.config
        self.client = TestClient(
            create_app(
                config,
                state=self.state,
                secrets_dir=self.box.secrets,
                data_dir=self.box.data,
                telegram=self.box.bot,
            )
        )

    def _apply(self, config: Config) -> list[str]:
        self.applied.append(config)
        return []


def test_a_token_turns_the_bot_on_and_offers_a_link_and_is_never_given_back(
    tmp_path: Path,
) -> None:
    api = Api(tmp_path, smart_home(enabled=False))
    answer = api.client.post("/telegram/token", json={"token": TOKEN})
    assert answer.status_code == 200, answer.text
    shown = answer.json()
    assert shown["enabled"] and shown["bot"] == "my_box_bot" and not shown["linked"]
    assert shown["link"].startswith("https://t.me/my_box_bot?start=")
    assert "<svg" in shown["qr_svg"] and shown["link_expires_at"] > api.box.clock.now
    assert load_config(api.path).telegram.enabled
    assert api.applied == []  # the router reads nothing of the bot
    assert TOKEN not in answer.text and TOKEN not in api.client.get("/telegram").text


def test_a_wrong_token_is_refused_with_its_reason(tmp_path: Path) -> None:
    api = Api(tmp_path, smart_home(enabled=False))
    malformed = api.client.post("/telegram/token", json={"token": "nonsense"})
    assert malformed.status_code == 422 and "bot's number" in malformed.text
    unknown = api.client.post("/telegram/token", json={"token": OTHER})
    assert unknown.status_code == 422 and "does not know this token" in unknown.text
    assert OTHER not in unknown.text
    assert not load_config(api.path).telegram.enabled


def test_settings_apply_live_and_a_bot_without_a_token_stays_off(tmp_path: Path) -> None:
    api = Api(tmp_path, smart_home(enabled=False))
    refused = api.client.put("/telegram", json={"enabled": True})
    assert refused.status_code == 422 and "vibedpn telegram set" in refused.text
    changed = api.client.put(
        "/telegram",
        json={
            "alert_after_seconds": 120,
            "timezone": "Asia/Yekaterinburg",
            "report_weekday": "friday",
            "report_hour": 9,
        },
    )
    assert changed.status_code == 200, changed.text
    shown = changed.json()
    assert (shown["alert_after_seconds"], shown["timezone"]) == (120, "Asia/Yekaterinburg")
    assert shown["report"] == {"enabled": True, "weekday": "friday", "hour": 9}
    saved = load_config(api.path).telegram
    assert saved.report.weekday is Weekday.FRIDAY and api.state.config.telegram == saved
    assert api.applied == []
    wrong = api.client.put("/telegram", json={"timezone": "Mars/Base"})
    assert wrong.status_code == 422 and "time zone" in wrong.text


def test_a_link_needs_a_token_and_a_test_needs_a_chat(tmp_path: Path) -> None:
    api = Api(tmp_path, smart_home())
    assert api.client.post("/telegram/link").status_code == 409
    assert api.client.post("/telegram/test").status_code == 409
    linked = Api(tmp_path / "linked", smart_home(), linked=True)
    assert linked.client.post("/telegram/test").status_code == 204
    assert linked.box.texts() == ["A test message from your VibeDPN box."]
    linked.box.telegram.unreachable = True
    failed = linked.client.post("/telegram/test")
    assert failed.status_code == 503 and "via tor: ConnectionRefusedError" in failed.text


# --- the CLI and doctor -------------------------------------------------------------------------


def view(**fields: object) -> TelegramView:
    base: dict[str, object] = {
        "enabled": True,
        "token_set": True,
        "bot": "my_box_bot",
        "linked": False,
        "chat": "",
        "linked_at": None,
        "link": None,
        "qr_svg": None,
        "link_expires_at": None,
        "alert_after_seconds": 60,
        "timezone": "Europe/Moscow",
        "report": TelegramReportView(enabled=True, weekday=Weekday.MONDAY, hour=10),
        "last_ok": None,
        "last_at": None,
        "message": "",
        "via": "",
        "waiting": 0,
    }
    return TelegramView.model_validate({**base, **fields})


def cli_box(tmp_path: Path) -> Path:
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    (tmp_path / "config.yaml").write_text(render_config(smart_home()), encoding="utf-8")
    return tmp_path


def test_set_takes_the_token_from_a_file_and_waits_for_the_chat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = cli_box(tmp_path)
    token_file = tmp_path / "token"
    token_file.write_text(TOKEN + "\n", encoding="utf-8")
    link = "https://t.me/my_box_bot?start=abc"
    given: list[str] = []

    def set_token(_port: int, token: str) -> TelegramView:
        given.append(token)
        return view(link=link, link_expires_at=9e9)

    monkeypatch.setattr(core_api, "set_telegram_token", set_token)
    monkeypatch.setattr(
        core_api, "get_telegram", lambda _port: view(linked=True, chat="@anna", linked_at=9e9)
    )
    monkeypatch.setattr("vibedpn.cli.time.sleep", lambda _seconds: None)
    answer = runner.invoke(
        cli.app, ["telegram", "set", "--token-file", str(token_file), "--dir", str(directory)]
    )
    assert answer.exit_code == 0, answer.output
    assert given == [TOKEN + "\n"] and TOKEN not in answer.output
    assert link in answer.output and "linked: @anna" in answer.output


def test_a_link_that_expires_unopened_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = cli_box(tmp_path)
    monkeypatch.setattr(
        core_api, "offer_telegram_link", lambda _port: view(link="https://t.me/x?start=y")
    )
    monkeypatch.setattr(core_api, "get_telegram", lambda _port: view())
    monkeypatch.setattr("vibedpn.cli.time.sleep", lambda _seconds: None)
    answer = runner.invoke(cli.app, ["telegram", "link", "--dir", str(directory)])
    assert answer.exit_code == 1 and "expired" in answer.output


def test_show_tells_whose_bot_where_it_writes_and_how_the_last_message_went(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = cli_box(tmp_path)
    shown = view(
        linked=True,
        chat="@anna",
        last_ok=False,
        last_at=START,
        message="api.telegram.org via tor: ConnectionRefusedError",
        via="via tor",
        waiting=2,
    )
    monkeypatch.setattr(core_api, "get_telegram", lambda _port: shown)
    answer = runner.invoke(cli.app, ["telegram", "show", "--dir", str(directory)])
    assert answer.exit_code == 0, answer.output
    assert answer.output.splitlines() == [
        "telegram on: @my_box_bot",
        "chat: @anna",
        "alerts after 60 s of silence; weekly report: monday 10:00 Europe/Moscow",
        "last message 2026-09-21 06:59 UTC via tor: not sent:"
        " api.telegram.org via tor: ConnectionRefusedError",
        "messages waiting: 2",
    ]


LINKED = TelegramSecrets(token=TOKEN, bot="my_box_bot", chat_id=CHAT, chat_name="@anna")


@pytest.mark.parametrize(
    ("facts", "verdict", "hint"),
    [
        (TelegramFacts(present=None), Verdict.WARN, "sudo vibedpn doctor"),
        (TelegramFacts(present=False), Verdict.FAIL, "vibedpn telegram set"),
        (TelegramFacts(present=True), Verdict.FAIL, "vibedpn telegram set"),  # broken file
        (
            TelegramFacts(present=True, secrets=TelegramSecrets(token=TOKEN, bot="my_box_bot")),
            Verdict.WARN,
            "vibedpn telegram link",
        ),
        (TelegramFacts(present=True, secrets=LINKED), Verdict.OK, ""),
        (
            TelegramFacts(
                present=True,
                secrets=LINKED,
                state=BotState(delivery=Delivery(last_ok=False, last_at=START, message="x")),
            ),
            Verdict.FAIL,
            "vibedpn telegram show",
        ),
        (
            TelegramFacts(
                present=True,
                secrets=LINKED,
                state=BotState(delivery=Delivery(last_ok=True, last_at=START, via="via tor")),
            ),
            Verdict.OK,
            "",
        ),
    ],
)
def test_doctor_tells_what_the_bot_lacks(facts: TelegramFacts, verdict: Verdict, hint: str) -> None:
    result = _telegram_result(facts)
    assert (result.name, result.verdict, result.hint) == ("telegram", verdict, hint)
    assert TOKEN not in result.detail
