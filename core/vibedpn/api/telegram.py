"""The Telegram bot of core (decision 31, docs/manuals/telegramBot.md).

One loop on core's event loop drains the events the journal hands over, looks at ddns and at the
changes the host applied for the panel, keeps a heartbeat, sends what ``engine/notices.py``
decided, and — while a link waits to be opened — asks Telegram for the ``/start`` that links a
chat. The calls to Telegram and to the node run in threads. The request threads of the API (a
token, a link, a test) share the state through a lock; the journal only appends to a deque, so a
watcher never waits for the bot.

The loop runs on every box whether the bot is on or not: turning it on in the panel needs no
restart. It keeps nothing on disk while ``telegram.enabled`` is off.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import sqlite3
import sys
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from vibedpn.api.background import failure, supervised
from vibedpn.api.traffic import ACCESS_TRAFFIC_DIR
from vibedpn.api.uplink import UplinkWatchers
from vibedpn.atomic import write_private
from vibedpn.config import Config
from vibedpn.engine.access import AccessError, list_people
from vibedpn.engine.apply import ApplyResult, apply_state
from vibedpn.engine.ddns import STATE_FILE as DDNS_STATE_FILE
from vibedpn.engine.ddns import DdnsState
from vibedpn.engine.ddns import load_state as load_ddns_state
from vibedpn.engine.events import Event
from vibedpn.engine.i18n import Catalog, Phrase
from vibedpn.engine.myst import MystError, ProviderStats, TequilaClient, provider_stats
from vibedpn.engine.notices import (
    HEARTBEAT_SECONDS,
    STATE_FILE,
    Delivery,
    NodeState,
    Notice,
    NoticeKind,
    PersonUse,
    ReportFacts,
    alert_due,
    close_period,
    delivered,
    enqueue,
    failed,
    forget_unwatched,
    last_slot,
    load_state,
    observe,
    observe_apply,
    observe_ddns,
    render,
    report_due,
    take_batch,
    wake,
)
from vibedpn.engine.telegram import (
    API_URL,
    API_URL_ENV,
    PRIVATE_CHAT,
    TIMEOUT_SECONDS,
    Endpoint,
    Lookup,
    TelegramError,
    TelegramSecrets,
    Transport,
    Update,
    call,
    endpoint,
    load_secrets,
    marked_request,
    parse_updates,
    route_to,
    save_secrets,
    start_code,
    via,
)
from vibedpn.engine.traffic import connect as traffic_connect
from vibedpn.engine.traffic import day_of
from vibedpn.engine.traffic import totals as traffic_totals

TICK_SECONDS = 1.0
LOOK_SECONDS = 30.0  # ddns.json and the result of `vibedpn apply` are looked at this often
LINK_SECONDS = 15 * 60  # a link to the bot waits this long for its /start
# getUpdates holds the request open this long when nothing comes ("Timeout in seconds for long
# polling", https://core.telegram.org/bots/api#getupdates): one request per poll through Tor.
POLL_SECONDS = 20
LINK_RETRY_SECONDS = 5.0
# token_urlsafe gives A-Z, a-z, 0-9, _ and -: what a deep link carries, 22 of its 64 characters.
LINK_CODE_BYTES = 16

Sleep = Callable[[float], Awaitable[None]]
StatsSource = Callable[[], ProviderStats]


@dataclass(frozen=True)
class LinkOffer:
    code: str
    expires_at: float


@dataclass(frozen=True)
class BotStatus:
    token_set: bool
    bot: str
    linked: bool
    chat: str
    linked_at: float | None
    offer: LinkOffer | None
    delivery: Delivery
    waiting: int


def link_url(bot: str, code: str) -> str:
    """The deep link that opens the bot and sends it ``/start <code>``."""
    return f"https://t.me/{bot}?start={code}"


def _node_stats() -> ProviderStats:
    client = TequilaClient()
    try:
        return provider_stats(client)
    finally:
        client.close()


def _log(message: str) -> None:
    sys.stderr.write(f"vibedpn-core: telegram: {message}\n")


class TelegramBot:
    """The bot of this box: its secrets, its state and the loop that keeps both."""

    def __init__(
        self,
        current: Callable[[], Config],
        *,
        secrets_dir: Path,
        data_dir: Path,
        catalog: Catalog,
        lookup: Lookup,
        inbox: deque[Event],
        watchers: UplinkWatchers | None = None,
        stats: StatsSource = _node_stats,
        where: Endpoint | None = None,
        transport: Transport = marked_request,
        clock: Callable[[], float] = time.time,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._current = current
        self._secrets_dir = secrets_dir
        self._data_dir = data_dir
        self._catalog = catalog
        self._lookup = lookup
        self._inbox = inbox
        self._watchers = watchers
        self._stats = stats
        self._where = where or endpoint(os.environ.get(API_URL_ENV, API_URL))
        self._transport = transport
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._secrets = load_secrets(secrets_dir)
        self._state = load_state(data_dir / STATE_FILE)
        self._saved_text = ""
        self._offer: LinkOffer | None = None
        self._listener: asyncio.Task[None] | None = None
        self._was_active = self._active(current())
        self._looked_at = float("-inf")
        self._logged = ""
        # Once per start of core, not per start of the loop: the loop starts again after a failure,
        # and its pause is not the box being off.
        wake(self._state, clock(), active=self._was_active)

    # --- what the request threads of the API ask -----------------------------------------------

    def status(self) -> BotStatus:
        with self._lock:
            known = self._secrets
            return BotStatus(
                token_set=known is not None,
                bot=known.bot if known is not None else "",
                linked=known is not None and known.chat_id is not None,
                chat=known.chat_name if known is not None else "",
                linked_at=known.linked_at if known is not None else None,
                offer=self._live_offer(self._clock()),
                delivery=self._state.delivery.model_copy(),
                waiting=len(self._state.outbox),
            )

    def set_token(self, token: str) -> LinkOffer:
        """Ask Telegram whose token it is, through the exit of the box, and keep it. The same
        token keeps its chat; another bot links its chat anew."""
        route = route_to(self._current(), self._where, self._lookup)
        me = call(self._where, route, token, "getMe", {}, transport=self._transport)
        username = me.get("username") if isinstance(me, dict) else None
        if not isinstance(username, str) or not username:
            raise TelegramError("getMe answered without the name of the bot")
        with self._lock:
            known = self._secrets
            if known is not None and known.token == token:
                kept = known.model_copy(update={"bot": username})
            else:
                kept = TelegramSecrets(token=token, bot=username)
            self._keep(kept)
            return self._new_offer()

    def offer_link(self) -> LinkOffer:
        """A new link that links whoever opens it and presses Start; the old one stops working."""
        with self._lock:
            if self._secrets is None:
                raise TelegramError("no bot token yet: vibedpn telegram set")
            return self._new_offer()

    def test(self) -> None:
        """Send a test message now, past the queue; the reason why not when it does not leave."""
        with self._lock:
            known = self._secrets
        if known is None or known.chat_id is None:
            raise TelegramError("no chat is linked yet: vibedpn telegram link")
        _via, error = self._send(self._current(), known, self._catalog.text(Phrase.TEST))
        if error is not None:
            raise error

    def _keep(self, kept: TelegramSecrets) -> None:
        save_secrets(self._secrets_dir, kept)
        self._secrets = kept

    def _new_offer(self) -> LinkOffer:
        self._offer = LinkOffer(
            secrets.token_urlsafe(LINK_CODE_BYTES), self._clock() + LINK_SECONDS
        )
        return self._offer

    def _live_offer(self, now: float) -> LinkOffer | None:
        offer = self._offer
        return offer if offer is not None and now < offer.expires_at else None

    def _active(self, config: Config) -> bool:
        known = self._secrets
        return config.telegram.enabled and known is not None and known.chat_id is not None

    # --- the loop ------------------------------------------------------------------------------

    async def run(self) -> None:
        try:
            while True:
                await self._tick()
                await self._sleep(TICK_SECONDS)
        finally:
            listener = self._listener
            if listener is not None:
                listener.cancel()
                await asyncio.gather(listener, return_exceptions=True)

    async def _tick(self) -> None:
        """One round; a stage that raised leaves the stages after it their turn."""
        config = self._current()
        now = self._clock()
        with self._guard("observing"):
            looked = self._look(config, now)
            with self._lock:
                self._step(config, now, looked)
        with self._guard("the report"):
            await self._report(config, now)
        with self._guard("sending"):
            await self._deliver(config, now)
        with self._guard("listening"):
            self._listener = self._listening(self._listener)
        with self._guard("keeping the state"):
            self._persist(config)

    @contextmanager
    def _guard(self, stage: str) -> Iterator[None]:
        """A stage that raised must not take their turn from the stages after it: core would start
        the whole loop again, and the same stage would fail first every time. The exception goes to
        the log — its class and place, not its text, which could quote a request, and a request
        carries the token."""
        try:
            yield
        except Exception as exc:
            self._log_once(f"{stage} failed: {failure(exc)}")

    def _look(
        self, config: Config, now: float
    ) -> tuple[DdnsState | None, ApplyResult | None] | None:
        """ddns and the result of the last change of the panel, every ``LOOK_SECONDS``."""
        if now - self._looked_at < LOOK_SECONDS:
            return None
        self._looked_at = now
        ddns_path = self._data_dir / DDNS_STATE_FILE
        ddns = load_ddns_state(ddns_path) if config.ddns.enabled and ddns_path.exists() else None
        return ddns, apply_state(self._data_dir, now).last

    def _step(
        self,
        config: Config,
        now: float,
        looked: tuple[DdnsState | None, ApplyResult | None] | None,
    ) -> None:
        state = self._state
        active = self._active(config)
        if active and not self._was_active:
            state.heartbeat = now  # just turned on or linked: no gap to tell of
        self._was_active = active
        if not active:
            state.outbox.clear()  # news for a bot that cannot tell it would be a backlog later
        while self._inbox:
            observe(state, self._inbox.popleft(), active=active)
        if self._watchers is not None:
            forget_unwatched(state, self._watchers.wanted(), now)
        if looked is not None:
            ddns, applied = looked
            observe_ddns(state, ddns, enabled=config.ddns.enabled, now=now, active=active)
            observe_apply(state, applied, now=now, active=active)
        alert_due(state, now, config.telegram.alert_after_seconds, active=active)
        if active and (state.heartbeat is None or now - state.heartbeat >= HEARTBEAT_SECONDS):
            state.heartbeat = now
        if active and state.period_since is None:
            state.period_since = now

    async def _report(self, config: Config, now: float) -> None:
        """The weekly report, once its moment on the owner's clock has passed."""
        schedule = config.telegram.report
        with self._lock:
            if not self._active(config) or not schedule.enabled:
                return
            zone = ZoneInfo(config.telegram.timezone)
            slot = last_slot(now, zone, schedule.weekday, schedule.hour)
            if not report_due(self._state, slot, now):
                return
            since = self._state.period_since if self._state.period_since is not None else now
        facts = await asyncio.to_thread(self._facts, config, since)
        with self._lock:
            report = close_period(self._state, now, slot, facts)
            enqueue(self._state, Notice(at=now, kind=NoticeKind.REPORT, report=report))

    def _facts(self, config: Config, since: float) -> ReportFacts:
        node = NodeState.OFF
        total: str | None = None
        if config.provider.enabled:
            try:
                identity = self._stats().identity
            except MystError:
                identity = None
            node = NodeState.SILENT if identity is None else NodeState.ON
            total = None if identity is None else identity.earnings_total_tokens.wei
        return ReportFacts(
            node=node,
            total_wei=total,
            exits=config.network is not None,
            people=self._people(since) if config.access.enabled else None,
            watches_address=config.ddns.enabled,
        )

    def _people(self, since: float) -> list[PersonUse] | None:
        """What each person of the access server used since the start of the period, by days."""
        try:
            names = {person.id: person.name for person in list_people(self._secrets_dir)}
            with closing(traffic_connect(self._data_dir / ACCESS_TRAFFIC_DIR)) as connection:
                used = traffic_totals(connection, day_of(since))
        except (AccessError, sqlite3.Error, OSError) as exc:
            self._log_once(f"the report goes without the access server: {exc}")
            return None
        return [
            PersonUse(name=names[total.public_key], amount=total.total_bytes)
            for total in used
            if total.public_key in names and total.total_bytes > 0
        ]

    async def _deliver(self, config: Config, now: float) -> None:
        with self._lock:
            known = self._secrets
            if known is None or not self._active(config):
                return
            zone = ZoneInfo(config.telegram.timezone)
            batch = take_batch(
                self._state, now, lambda notice: render(notice, self._catalog, zone, now)
            )
        if batch is None:
            return
        count, text = batch
        sent_via, error = await asyncio.to_thread(self._send, config, known, text)
        with self._lock:
            if error is None:
                delivered(self._state, count, self._clock(), sent_via)
                self._logged = ""
            else:
                failed(self._state, self._clock(), str(error), sent_via, error.retry_after)
                self._log_once(f"a message waits: {error}")

    def _send(
        self, config: Config, known: TelegramSecrets, text: str
    ) -> tuple[str, TelegramError | None]:
        """One message to the linked chat, and the exit it took (an uplink key, or direct)."""
        try:
            route = route_to(config, self._where, self._lookup)
        except TelegramError as exc:
            return "", exc
        try:
            call(
                self._where,
                route,
                known.token,
                "sendMessage",
                {"chat_id": known.chat_id, "text": text},
                transport=self._transport,
            )
        except TelegramError as exc:
            return via(route), exc
        return via(route), None

    def _listening(self, task: asyncio.Task[None] | None) -> asyncio.Task[None] | None:
        """One listener while a link waits to be opened, none otherwise."""
        with self._lock:
            waiting = self._live_offer(self._clock()) is not None and self._secrets is not None
        if not waiting:
            if task is not None and not task.done():
                task.cancel()
            return None
        if task is None or task.done():
            return asyncio.ensure_future(supervised("telegram link listener", self._listen))
        return task

    async def _listen(self) -> None:
        """Ask Telegram for new messages while a link waits; the ``/start`` that carries its code
        links the chat it came from. Each message is checked against the link waiting at that
        moment, so a new link never loses its ``/start`` to the listener of the old one."""
        offset: int | None = None
        while True:
            with self._lock:
                known = self._secrets
                waiting = self._live_offer(self._clock())
            if known is None or waiting is None:
                return
            try:
                updates = await asyncio.to_thread(self._updates, known.token, offset)
            except TelegramError as exc:
                self._log_once(f"cannot hear the bot: {exc}")
                await self._sleep(LINK_RETRY_SECONDS)
                continue
            for update in updates:
                offset = max(offset or 0, update.id + 1)
                with self._lock:
                    if self._link(update):
                        return

    def _updates(self, token: str, offset: int | None) -> list[Update]:
        route = route_to(self._current(), self._where, self._lookup)
        payload: dict[str, object] = {"timeout": POLL_SECONDS, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset  # confirms everything before it
        result = call(
            self._where,
            route,
            token,
            "getUpdates",
            payload,
            timeout=POLL_SECONDS + TIMEOUT_SECONDS,
            transport=self._transport,
        )
        return parse_updates(result)

    def _link(self, update: Update) -> bool:
        """The chat of a private ``/start <code>`` of the waiting link becomes the bot's chat."""
        now = self._clock()
        offer = self._live_offer(now)
        code = start_code(update.text)
        known = self._secrets
        if (
            offer is None
            or known is None
            or update.chat_id is None
            or update.chat_type != PRIVATE_CHAT
            or code is None
            or not secrets.compare_digest(code, offer.code)
        ):
            return False
        try:
            self._keep(
                known.model_copy(
                    update={
                        "chat_id": update.chat_id,
                        "chat_name": update.chat_name,
                        "linked_at": now,
                    }
                )
            )
        except OSError as exc:
            self._log_once(f"cannot keep the linked chat: {exc.strerror or exc}")
            return False
        self._offer = None
        enqueue(self._state, Notice(at=now, kind=NoticeKind.LINKED))
        return True

    def _persist(self, config: Config) -> None:
        """Write the state when it changed, and only while the bot is on."""
        if not config.telegram.enabled:
            return
        with self._lock:
            text = self._state.model_dump_json(indent=2)
        if text == self._saved_text:
            return
        try:
            write_private(self._data_dir / STATE_FILE, text + "\n")
        except OSError as exc:
            self._log_once(f"cannot keep its state: {exc.strerror or exc}")
            return
        self._saved_text = text

    def _log_once(self, message: str) -> None:
        if message != self._logged:
            _log(message)
            self._logged = message
