"""What the Telegram bot tells the owner, and when (decision 31): pure, so every rule is a test.

The bot hears the event journal (an exit or the access point went silent or came back), looks at
what other watchers keep (ddns, the result of a change made in the panel) and at its own heartbeat,
and turns that into notices. A notice is data; its phrase is built when it is sent, in the
language of the box (``engine/i18n.py``). The functions change the state they are given in place;
``load_state`` alone reads a file, for core and for ``vibedpn doctor`` alike.

The rules:
- an outage is news only when it lasts: an exit or the access point silent for
  ``telegram.alert_after_seconds``, ddns failing across two of its rounds;
- that it is over is told only after it was told that it began; when the first could not leave
  before it was over (Telegram goes out through that very exit), the two become one notice;
- notices arriving within ``MERGE_SECONDS`` of each other leave as one message;
- nothing is queued for a bot that is off or has no chat: the owner gets news, not a backlog.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, tzinfo
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from vibedpn.config import Weekday
from vibedpn.engine.apply import ApplyResult
from vibedpn.engine.ddns import INTERVAL_SECONDS as DDNS_INTERVAL_SECONDS
from vibedpn.engine.ddns import DdnsState
from vibedpn.engine.events import Event, EventAction, EventKind
from vibedpn.engine.i18n import Catalog, Phrase
from vibedpn.engine.myst import WEI_PER_MYST

STATE_FILE = "telegram.json"  # in core's data directory: the queue, the outages, the heartbeat
MERGE_SECONDS = 10.0
HEARTBEAT_SECONDS = 60.0
# A restart of core takes seconds; a box that missed three heartbeats was off, or core was.
OFFLINE_AFTER_SECONDS = 3 * HEARTBEAT_SECONDS
# ddns looks at the address every few minutes: one failed round may be a blink of ipify.
DDNS_ALERT_AFTER_SECONDS = 2 * DDNS_INTERVAL_SECONDS
MAX_OUTBOX = 100
# "1-4096 characters after entities parsing" (https://core.telegram.org/bots/api#sendmessage)
MESSAGE_CHARS = 4096
BACKOFF_SECONDS = 5.0
MAX_BACKOFF_SECONDS = 300.0
MYST_PLACES = 4
# A report of a period shorter than this waits for the next slot: a bot turned on at 09:59 must
# not send a "weekly" report of one minute at 10:00.
SHORTEST_PERIOD_SECONDS = 24 * 3600
LIST_SEPARATOR = ", "
NOTICE_SEPARATOR = "\n\n"


class Subject(StrEnum):
    """What can go silent."""

    UPLINK = "uplink"  # name: the uplink key
    WIFI = "wifi"  # name: the interface of the access point
    DDNS = "ddns"  # name: empty


class NoticeKind(StrEnum):
    DOWN = "down"  # since
    BACK = "back"  # since, until
    OUTAGE = "outage"  # since, until: it began and ended before the first could leave
    ADDRESS = "address"  # old, new
    BOX_BACK = "box_back"  # since: the last heartbeat, until: the start
    APPLY_FAILED = "apply_failed"  # reason
    LINKED = "linked"
    REPORT = "report"  # report


# These leave at once: nothing is worth waiting for to go with them.
IMMEDIATE = frozenset({NoticeKind.LINKED, NoticeKind.REPORT})


class NodeState(StrEnum):
    OFF = "off"
    SILENT = "silent"  # on, but TequilAPI did not answer
    ON = "on"


class PersonUse(BaseModel):
    name: str
    amount: int  # bytes both ways


class ReportFacts(BaseModel):
    """What the report needs from outside the bot, gathered when it is due."""

    node: NodeState
    total_wei: str | None = None  # the node's total earnings; None: off or silent
    exits: bool  # the box routes a LAN through exits: their silence is part of the report
    people: list[PersonUse] | None = None  # None: no access server, or its totals unreadable
    watches_address: bool  # ddns is on: someone looks at the public address


class Report(BaseModel):
    """The week, as the report tells it; a field is ``None`` when this box has no such thing."""

    since: float
    until: float
    node: NodeState
    total_wei: str | None = None
    earned_wei: str | None = None  # None: no total from the start of the period to compare with
    downtime: dict[str, float] | None = None  # uplink → seconds silent; None: a box without exits
    people: list[PersonUse] | None = None  # None: no access server, or its totals unreadable
    address_changes: int | None = None  # None: ddns is off, nobody watches the address


class Notice(BaseModel):
    at: float
    kind: NoticeKind
    subject: Subject | None = None
    name: str = ""
    since: float | None = None
    until: float | None = None
    reason: str = ""
    old: str = ""
    new: str = ""
    report: Report | None = None


class Outage(BaseModel):
    subject: Subject
    name: str
    since: float
    counted_from: float  # the silence before this moment is already in the downtime of a report
    alerted: bool = False
    reason: str = ""


class Delivery(BaseModel):
    last_ok: bool | None = None
    last_at: float | None = None
    message: str = ""
    via: str = ""  # the exit of the last attempt: an uplink key or "direct"; empty when not known
    failures: int = 0
    retry_at: float = 0.0


class BotState(BaseModel):
    """What the bot keeps between starts of core (``data/core/telegram.json``)."""

    heartbeat: float | None = None
    outbox: list[Notice] = Field(default_factory=list)
    outages: dict[str, Outage] = Field(default_factory=dict)
    period_since: float | None = None  # the start of the period the next report covers
    reported_slot: float | None = None  # the scheduled moment the last report was for
    downtime: dict[str, float] = Field(default_factory=dict)  # uplink → seconds in the period
    address_changes: int = 0
    earnings_wei: str | None = None  # the node's total at the start of the period
    ddns_ip: str | None = None  # the public address ddns reported last
    apply_seen: float | None = None  # the request of the last `vibedpn apply` result looked at
    delivery: Delivery = Field(default_factory=Delivery)


def load_state(path: Path) -> BotState:
    """What core kept; a missing or broken file is a bot that starts afresh."""
    try:
        return BotState.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return BotState()


def _key(subject: Subject, name: str) -> str:
    return f"{subject}:{name}"


def enqueue(state: BotState, notice: Notice) -> None:
    """Queue a notice. That an outage is over, while the notice that it began still waits, makes
    the two one notice with both times; the oldest go first when the queue is full."""
    if notice.kind is NoticeKind.BACK:
        for index, waiting in enumerate(state.outbox):
            if (
                waiting.kind is NoticeKind.DOWN
                and waiting.subject is notice.subject
                and waiting.name == notice.name
            ):
                state.outbox[index] = notice.model_copy(
                    update={"kind": NoticeKind.OUTAGE, "reason": waiting.reason or notice.reason}
                )
                return
    state.outbox.append(notice)
    del state.outbox[:-MAX_OUTBOX]


def _open(state: BotState, subject: Subject, name: str, since: float, reason: str = "") -> None:
    key = _key(subject, name)
    outage = state.outages.get(key)
    if outage is None:
        state.outages[key] = Outage(
            subject=subject, name=name, since=since, counted_from=since, reason=reason
        )
    elif reason:
        outage.reason = reason


def _close(state: BotState, subject: Subject, name: str, until: float, *, active: bool) -> None:
    """The outage is over: its silence goes to the downtime of the period, and the owner hears it
    ended when they heard it began."""
    outage = state.outages.pop(_key(subject, name), None)
    if outage is None:
        return
    if subject is Subject.UPLINK:
        state.downtime[name] = state.downtime.get(name, 0.0) + max(0.0, until - outage.counted_from)
    if outage.alerted and active:
        enqueue(
            state,
            Notice(
                at=until,
                kind=NoticeKind.BACK,
                subject=subject,
                name=name,
                since=outage.since,
                until=until,
                reason=outage.reason,
            ),
        )


def observe(state: BotState, event: Event, *, active: bool) -> None:
    """An event of the journal. The access point is proven up by a client connecting to it, too:
    hostapd tells ``AP-ENABLED`` only to whoever listens at that moment, and after a restart of
    hostapd the watcher of core attaches too late to hear it."""
    if event.kind is EventKind.UPLINK:
        if event.action is EventAction.GATEWAY_SILENT:
            _open(state, Subject.UPLINK, event.subject, event.time)
        elif event.action is EventAction.GATEWAY_ANSWERS:
            _close(state, Subject.UPLINK, event.subject, event.time, active=active)
    elif event.kind is EventKind.WIFI:
        if event.action is EventAction.AP_DISABLED:
            _open(state, Subject.WIFI, event.subject, event.time)
        elif event.action is EventAction.AP_ENABLED:
            _close(state, Subject.WIFI, event.subject, event.time, active=active)
        elif event.action is EventAction.CLIENT_CONNECTED:
            for outage in [item for item in state.outages.values() if item.subject is Subject.WIFI]:
                _close(state, Subject.WIFI, outage.name, event.time, active=active)


def forget_unwatched(state: BotState, wanted: Iterable[str], now: float) -> None:
    """An exit no longer in use has no watcher to say it is back: its outage ends quietly."""
    kept = set(wanted)
    for outage in list(state.outages.values()):
        if outage.subject is Subject.UPLINK and outage.name not in kept:
            _close(state, Subject.UPLINK, outage.name, now, active=False)


def alert_due(state: BotState, now: float, threshold: float, *, active: bool) -> None:
    """Outages that have lasted long enough to be news; nothing is told to a bot that cannot tell,
    and such an outage is told once it can."""
    if not active:
        return
    for outage in state.outages.values():
        wait = DDNS_ALERT_AFTER_SECONDS if outage.subject is Subject.DDNS else threshold
        if not outage.alerted and now - outage.since >= wait:
            outage.alerted = True
            enqueue(
                state,
                Notice(
                    at=now,
                    kind=NoticeKind.DOWN,
                    subject=outage.subject,
                    name=outage.name,
                    since=outage.since,
                    reason=outage.reason,
                ),
            )


def observe_ddns(
    state: BotState, ddns: DdnsState | None, *, enabled: bool, now: float, active: bool
) -> None:
    """ddns fails when the service refused the last call or the address could not be looked at;
    a public address that moved is news of its own, and it is counted for the report."""
    if not enabled or ddns is None:
        state.outages.pop(_key(Subject.DDNS, ""), None)
        state.ddns_ip = None
        return
    if ddns.address_error or ddns.last_ok is False:
        _open(state, Subject.DDNS, "", now, ddns.address_error or ddns.message)
    else:
        _close(state, Subject.DDNS, "", now, active=active)
    if ddns.public_ip is None:
        return
    if state.ddns_ip is not None and ddns.public_ip != state.ddns_ip:
        state.address_changes += 1
        if active:
            enqueue(
                state,
                Notice(at=now, kind=NoticeKind.ADDRESS, old=state.ddns_ip, new=ddns.public_ip),
            )
    state.ddns_ip = ddns.public_ip


def observe_apply(state: BotState, result: ApplyResult | None, *, now: float, active: bool) -> None:
    """A change made in the panel that the host could not apply. The first look only remembers
    where the results stand: an old failure is not news."""
    if result is None:
        return
    seen, state.apply_seen = state.apply_seen, result.requested_at
    if seen is None or seen == result.requested_at or result.ok or not active:
        return
    enqueue(state, Notice(at=now, kind=NoticeKind.APPLY_FAILED, reason=result.message))


def wake(state: BotState, now: float, *, active: bool) -> None:
    """core starts: a heartbeat older than ``OFFLINE_AFTER_SECONDS`` means the box was off."""
    last = state.heartbeat
    if active and last is not None and now - last >= OFFLINE_AFTER_SECONDS:
        enqueue(state, Notice(at=now, kind=NoticeKind.BOX_BACK, since=last, until=now))
    state.heartbeat = now


def last_slot(now: float, zone: tzinfo, weekday: Weekday, hour: int) -> float:
    """The latest scheduled moment of the report at or before ``now``, on the owner's clock."""
    local = datetime.fromtimestamp(now, zone)
    back = (local.weekday() - list(Weekday).index(weekday)) % 7
    slot = (local - timedelta(days=back)).replace(hour=hour, minute=0, second=0, microsecond=0)
    if slot > local:
        slot -= timedelta(days=7)
    return slot.timestamp()


def report_due(state: BotState, slot: float, now: float) -> bool:
    """Whether the report of ``slot`` goes now. The first slot the bot meets only marks where it
    stands; a period shorter than ``SHORTEST_PERIOD_SECONDS`` goes with the next slot."""
    if state.reported_slot is None:
        state.reported_slot = slot
        return False
    if slot <= state.reported_slot:
        return False
    since = state.period_since if state.period_since is not None else now
    if slot - since < SHORTEST_PERIOD_SECONDS:
        state.reported_slot = slot
        return False
    return True


def close_period(state: BotState, now: float, slot: float, facts: ReportFacts) -> Report:
    """The report of the period that ends now: its downtime (an exit still silent counts up to
    now), its count of address changes, what the node earned since the last total; the next period
    starts empty."""
    for outage in state.outages.values():
        if outage.subject is Subject.UPLINK:
            state.downtime[outage.name] = state.downtime.get(outage.name, 0.0) + max(
                0.0, now - outage.counted_from
            )
            outage.counted_from = now
    report = Report(
        since=state.period_since if state.period_since is not None else now,
        until=now,
        node=facts.node,
        total_wei=facts.total_wei,
        earned_wei=_earned(state.earnings_wei, facts.total_wei),
        downtime={name: seconds for name, seconds in state.downtime.items() if seconds >= 1}
        if facts.exits
        else None,
        people=facts.people,
        address_changes=state.address_changes if facts.watches_address else None,
    )
    state.downtime = {}
    state.address_changes = 0
    state.period_since = now
    state.reported_slot = slot
    if facts.total_wei is not None:
        state.earnings_wei = facts.total_wei
    return report


def _earned(before: str | None, total: str | None) -> str | None:
    if before is None or total is None:
        return None
    try:
        return str(max(0, int(total) - int(before)))
    except ValueError:
        return None


Render = Callable[[Notice], str]


def take_batch(state: BotState, now: float, render: Render) -> tuple[int, str] | None:
    """The notices ready to leave as one message, and its text; ``None`` while there are none or
    the last failure asks to wait."""
    if not state.outbox or now < state.delivery.retry_at:
        return None
    first = state.outbox[0]
    if first.kind not in IMMEDIATE and now - first.at < MERGE_SECONDS:
        return None
    texts: list[str] = []
    length = 0
    for notice in state.outbox:
        text = render(notice)
        added = len(text) + (len(NOTICE_SEPARATOR) if texts else 0)
        if texts and length + added > MESSAGE_CHARS:
            break
        texts.append(text)
        length += added
    return len(texts), NOTICE_SEPARATOR.join(texts)[:MESSAGE_CHARS]


def delivered(state: BotState, count: int, now: float, via: str) -> None:
    del state.outbox[:count]
    state.delivery = Delivery(last_ok=True, last_at=now, via=via)


def failed(
    state: BotState, now: float, message: str, via: str, retry_after: float | None = None
) -> None:
    """The message stays queued: a pause Telegram asked for, or one that doubles with every
    failure up to ``MAX_BACKOFF_SECONDS``."""
    failures = state.delivery.failures + 1
    pause = min(MAX_BACKOFF_SECONDS, BACKOFF_SECONDS * 2 ** (failures - 1))
    state.delivery = Delivery(
        last_ok=False,
        last_at=now,
        message=message,
        via=via,
        failures=failures,
        retry_at=now + (retry_after if retry_after is not None else pause),
    )


PHRASES: dict[tuple[NoticeKind, Subject], Phrase] = {
    (NoticeKind.DOWN, Subject.UPLINK): Phrase.UPLINK_DOWN,
    (NoticeKind.BACK, Subject.UPLINK): Phrase.UPLINK_BACK,
    (NoticeKind.OUTAGE, Subject.UPLINK): Phrase.UPLINK_OUTAGE,
    (NoticeKind.DOWN, Subject.WIFI): Phrase.WIFI_DOWN,
    (NoticeKind.BACK, Subject.WIFI): Phrase.WIFI_BACK,
    (NoticeKind.OUTAGE, Subject.WIFI): Phrase.WIFI_OUTAGE,
    (NoticeKind.DOWN, Subject.DDNS): Phrase.DDNS_DOWN,
    (NoticeKind.BACK, Subject.DDNS): Phrase.DDNS_BACK,
    (NoticeKind.OUTAGE, Subject.DDNS): Phrase.DDNS_OUTAGE,
}


def render(notice: Notice, catalog: Catalog, zone: tzinfo, now: float) -> str:
    """The phrase of a notice in the language of the catalog, with times on the owner's clock."""
    since = notice.since if notice.since is not None else notice.at
    until = notice.until if notice.until is not None else notice.at
    times = {
        "time": catalog.time(since, zone, now),
        "from": catalog.time(since, zone, now),
        "to": catalog.time(until, zone, now),
        "duration": catalog.duration(until - since),
    }
    if notice.subject is not None:
        phrase = PHRASES[(notice.kind, notice.subject)]
        return catalog.text(phrase, name=notice.name, reason=notice.reason, **times)
    if notice.report is not None:
        return render_report(notice.report, catalog, zone)
    simple = {
        NoticeKind.ADDRESS: lambda: catalog.text(
            Phrase.ADDRESS_CHANGED, old=notice.old, new=notice.new
        ),
        NoticeKind.BOX_BACK: lambda: catalog.text(Phrase.BOX_BACK, **times),
        NoticeKind.APPLY_FAILED: lambda: catalog.text(Phrase.APPLY_FAILED, reason=notice.reason),
        NoticeKind.LINKED: lambda: catalog.text(Phrase.LINKED),
    }
    return simple[notice.kind]()


def _myst(catalog: Catalog, wei: str) -> str:
    try:
        return catalog.decimal(Decimal(wei) / WEI_PER_MYST, MYST_PLACES)
    except InvalidOperation:
        return wei


def render_report(report: Report, catalog: Catalog, zone: tzinfo) -> str:
    lines = [
        catalog.text(
            Phrase.REPORT_TITLE,
            **{"from": catalog.date(report.since, zone), "to": catalog.date(report.until, zone)},
        )
    ]
    if report.node is NodeState.OFF:
        lines.append(catalog.text(Phrase.REPORT_NODE_OFF))
    elif report.node is NodeState.SILENT or report.total_wei is None:
        lines.append(catalog.text(Phrase.REPORT_NODE_SILENT))
    elif report.earned_wei is None:
        lines.append(catalog.text(Phrase.REPORT_NODE_TOTAL, total=_myst(catalog, report.total_wei)))
    else:
        lines.append(
            catalog.text(
                Phrase.REPORT_NODE_EARNED,
                earned=_myst(catalog, report.earned_wei),
                total=_myst(catalog, report.total_wei),
            )
        )
    if report.downtime is not None:
        if report.downtime:
            items = sorted(report.downtime.items(), key=lambda item: (-item[1], item[0]))
            listed = LIST_SEPARATOR.join(
                catalog.text(Phrase.REPORT_EXIT, name=name, duration=catalog.duration(seconds))
                for name, seconds in items
            )
            lines.append(catalog.text(Phrase.REPORT_EXITS_DOWN, list=listed))
        else:
            lines.append(catalog.text(Phrase.REPORT_EXITS_FINE))
    if report.people is not None:
        if report.people:
            listed = LIST_SEPARATOR.join(
                catalog.text(
                    Phrase.REPORT_PERSON, name=person.name, amount=catalog.size(person.amount)
                )
                for person in report.people
            )
            lines.append(catalog.text(Phrase.REPORT_PEOPLE_USED, list=listed))
        else:
            lines.append(catalog.text(Phrase.REPORT_PEOPLE_NONE))
    if report.address_changes is not None:
        lines.append(catalog.text(Phrase.REPORT_ADDRESS_CHANGES, count=report.address_changes))
    return "\n".join(lines)
