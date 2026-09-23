"""What the Telegram bot tells, and when: thresholds, the order of down and back, merging, the
report and its week, the phrases."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from vibedpn.config import Weekday
from vibedpn.engine.apply import ApplyResult
from vibedpn.engine.ddns import DdnsState
from vibedpn.engine.events import Event, EventAction, EventKind
from vibedpn.engine.i18n import base_catalog, load_catalog
from vibedpn.engine.notices import (
    DDNS_ALERT_AFTER_SECONDS,
    MAX_BACKOFF_SECONDS,
    MERGE_SECONDS,
    MESSAGE_CHARS,
    BotState,
    NodeState,
    Notice,
    NoticeKind,
    PersonUse,
    ReportFacts,
    Subject,
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
    render_report,
    report_due,
    take_batch,
    wake,
)

NOW = 1_790_000_000.0  # 2026-09-21 14:13:20 UTC
THRESHOLD = 60.0
UTC = ZoneInfo("UTC")
MOSCOW = ZoneInfo("Europe/Moscow")
LOCALES = Path(__file__).resolve().parents[2] / "ui" / "locales"
WEI = 10**18


def uplink(key: str, at: float, *, alive: bool) -> Event:
    action = EventAction.GATEWAY_ANSWERS if alive else EventAction.GATEWAY_SILENT
    return Event(at, EventKind.UPLINK, key, action)


def wifi(subject: str, at: float, action: EventAction) -> Event:
    return Event(at, EventKind.WIFI, subject, action)


def kinds(state: BotState) -> list[tuple[NoticeKind, str]]:
    return [(notice.kind, notice.name) for notice in state.outbox]


def text(notice: Notice, now: float = NOW) -> str:
    return render(notice, base_catalog(), UTC, now)


# --- outages ------------------------------------------------------------------------------------


def test_a_flap_shorter_than_the_threshold_is_not_news_but_counts_as_downtime() -> None:
    state = BotState()
    observe(state, uplink("tor", NOW, alive=False), active=True)
    alert_due(state, NOW + 30, THRESHOLD, active=True)
    observe(state, uplink("tor", NOW + 40, alive=True), active=True)
    alert_due(state, NOW + 120, THRESHOLD, active=True)
    assert state.outbox == [] and state.outages == {}
    assert state.downtime == {"tor": 40.0}


def test_a_long_silence_is_told_once_and_its_end_only_after_it() -> None:
    state = BotState()
    observe(state, uplink("tor", NOW, alive=False), active=True)
    alert_due(state, NOW + THRESHOLD, THRESHOLD, active=True)
    alert_due(state, NOW + 2 * THRESHOLD, THRESHOLD, active=True)
    assert kinds(state) == [(NoticeKind.DOWN, "tor")]
    assert text(state.outbox[0]) == "Exit tor has not answered since 14:13."
    delivered(state, 1, NOW + 70, "direct")
    observe(state, uplink("tor", NOW + 300, alive=True), active=True)
    assert kinds(state) == [(NoticeKind.BACK, "tor")]
    assert text(state.outbox[0]) == "Exit tor answers again after 5 min of silence."
    assert state.downtime == {"tor": 300.0}


def test_when_the_first_could_not_leave_before_the_end_the_two_become_one() -> None:
    """Telegram goes out through that very exit: the owner hears it all at once, with both
    times, instead of an old alarm followed by its all-clear."""
    state = BotState()
    observe(state, uplink("tor", NOW, alive=False), active=True)
    alert_due(state, NOW + THRESHOLD, THRESHOLD, active=True)
    observe(state, uplink("tor", NOW + 200, alive=True), active=True)
    assert kinds(state) == [(NoticeKind.OUTAGE, "tor")]
    assert text(state.outbox[0]) == "Exit tor was silent for 3 min 20 s, 14:13 to 14:16."


def test_nothing_is_told_to_a_bot_that_cannot_tell_and_it_is_told_once_it_can() -> None:
    state = BotState()
    observe(state, uplink("dpn", NOW, alive=False), active=False)
    alert_due(state, NOW + 2 * THRESHOLD, THRESHOLD, active=False)
    assert state.outbox == [] and not state.outages["uplink:dpn"].alerted
    alert_due(state, NOW + 3 * THRESHOLD, THRESHOLD, active=True)
    assert kinds(state) == [(NoticeKind.DOWN, "dpn")]
    # an outage that was never told ends without a word
    other = BotState()
    observe(other, uplink("dpn", NOW, alive=False), active=False)
    observe(other, uplink("dpn", NOW + 600, alive=True), active=True)
    assert other.outbox == []


def test_the_access_point_is_proven_up_by_a_client_connecting_to_it() -> None:
    """hostapd tells AP-ENABLED only to whoever listens at that moment: after its restart the
    watcher of core attaches too late, and a client connecting is the proof that is left."""
    state = BotState()
    observe(state, wifi("wlp2s0", NOW, EventAction.AP_DISABLED), active=True)
    alert_due(state, NOW + THRESHOLD, THRESHOLD, active=True)
    assert text(state.outbox[0]) == "The Wi-Fi access point wlp2s0 has been off since 14:13."
    delivered(state, 1, NOW + 70, "direct")
    observe(state, wifi("aa:bb:cc:dd:ee:01", NOW + 90, EventAction.CLIENT_CONNECTED), active=True)
    assert kinds(state) == [(NoticeKind.BACK, "wlp2s0")]
    assert state.outages == {} and state.downtime == {}  # the report counts exits only


def test_an_exit_no_longer_in_use_ends_its_outage_quietly() -> None:
    state = BotState()
    observe(state, uplink("tor", NOW, alive=False), active=True)
    alert_due(state, NOW + THRESHOLD, THRESHOLD, active=True)
    delivered(state, 1, NOW + 70, "direct")
    forget_unwatched(state, ["dpn"], NOW + 100)
    assert state.outages == {} and state.outbox == [] and state.downtime == {"tor": 100.0}


# --- ddns, the panel, the heartbeat -----------------------------------------------------------


def ddns(**fields: object) -> DdnsState:
    known = {"public_ip": "203.0.113.5", "told_ip": "203.0.113.5"}
    return DdnsState.model_validate({**known, **fields})


def test_ddns_is_news_after_two_of_its_rounds_and_its_reason_goes_along() -> None:
    state = BotState()
    observe_ddns(state, ddns(last_ok=True), enabled=True, now=NOW, active=True)
    observe_ddns(state, ddns(last_ok=False, message="200 KO"), enabled=True, now=NOW, active=True)
    alert_due(state, NOW + DDNS_ALERT_AFTER_SECONDS - 1, THRESHOLD, active=True)
    assert state.outbox == []  # one failed round is no news: the next one may work
    alert_due(state, NOW + DDNS_ALERT_AFTER_SECONDS, THRESHOLD, active=True)
    assert text(state.outbox[0], NOW + DDNS_ALERT_AFTER_SECONDS) == (
        "The DNS name of the box has not followed its address since 14:13: 200 KO"
    )
    delivered(state, 1, NOW + 700, "direct")
    observe_ddns(state, ddns(last_ok=True), enabled=True, now=NOW + 900, active=True)
    assert kinds(state) == [(NoticeKind.BACK, "")]


def test_a_failed_look_at_the_address_is_a_failure_of_ddns_too() -> None:
    state = BotState()
    blind = ddns(last_ok=True, address_error="no public address: ConnectTimeout")
    observe_ddns(state, blind, enabled=True, now=NOW, active=True)
    assert state.outages["ddns:"].reason == "no public address: ConnectTimeout"


def test_a_new_public_address_is_told_and_counted() -> None:
    state = BotState()
    observe_ddns(state, ddns(last_ok=True), enabled=True, now=NOW, active=True)
    assert state.outbox == [] and state.ddns_ip == "203.0.113.5"  # the first look only learns
    moved = ddns(public_ip="198.51.100.7", last_ok=True)
    observe_ddns(state, moved, enabled=True, now=NOW + 300, active=True)
    assert text(state.outbox[0]) == (
        "The public address of the box changed: 203.0.113.5 → 198.51.100.7."
    )
    assert state.address_changes == 1


def test_ddns_turned_off_forgets_its_outage_and_its_address() -> None:
    state = BotState()
    observe_ddns(state, ddns(last_ok=False, message="KO"), enabled=True, now=NOW, active=True)
    observe_ddns(state, None, enabled=False, now=NOW + 60, active=True)
    assert state.outages == {} and state.ddns_ip is None


def test_a_change_of_the_panel_that_failed_is_told_once_and_an_old_one_never() -> None:
    state = BotState()
    old = ApplyResult(requested_at=1.0, finished_at=2.0, ok=False, message="old")
    observe_apply(state, old, now=NOW, active=True)
    assert state.outbox == []  # the first look only learns where the results stand
    new = ApplyResult(requested_at=3.0, finished_at=4.0, ok=False, message="compose failed")
    observe_apply(state, new, now=NOW, active=True)
    observe_apply(state, new, now=NOW + 30, active=True)
    assert [notice.reason for notice in state.outbox] == ["compose failed"]
    assert text(state.outbox[0]) == "A change made in the panel was not applied: compose failed"
    fine = ApplyResult(requested_at=5.0, finished_at=6.0, ok=True, message="")
    observe_apply(state, fine, now=NOW + 60, active=True)
    assert len(state.outbox) == 1


def test_a_gap_in_the_heartbeat_says_the_box_was_off() -> None:
    state = BotState(heartbeat=NOW - 3600)
    wake(state, NOW, active=True)
    assert kinds(state) == [(NoticeKind.BOX_BACK, "")]
    assert text(state.outbox[0]) == "The box is back: it was off for 1 h, 13:13 to 14:13."
    assert state.heartbeat == NOW
    restarted = BotState(heartbeat=NOW - 20)  # core recreated by `vibedpn up`
    wake(restarted, NOW, active=True)
    assert restarted.outbox == []
    silent = BotState(heartbeat=NOW - 3600)
    wake(silent, NOW, active=False)
    assert silent.outbox == []


# --- the report ------------------------------------------------------------------------------


def moment(zone: ZoneInfo, year: int, month: int, day: int, hour: int, minute: int) -> float:
    return datetime(year, month, day, hour, minute, tzinfo=zone).timestamp()


def test_the_moment_of_the_report_is_on_the_owners_clock() -> None:
    wednesday = moment(MOSCOW, 2026, 9, 23, 12, 0)
    assert last_slot(wednesday, MOSCOW, Weekday.MONDAY, 10) == moment(MOSCOW, 2026, 9, 21, 10, 0)
    before = moment(MOSCOW, 2026, 9, 21, 9, 59)
    assert last_slot(before, MOSCOW, Weekday.MONDAY, 10) == moment(MOSCOW, 2026, 9, 14, 10, 0)
    on_time = moment(MOSCOW, 2026, 9, 21, 10, 0)
    assert last_slot(on_time, MOSCOW, Weekday.MONDAY, 10) == on_time
    # the same instant is still Sunday evening in Chicago
    chicago = ZoneInfo("America/Chicago")
    assert last_slot(on_time, chicago, Weekday.SUNDAY, 20) == moment(chicago, 2026, 9, 20, 20, 0)


def test_the_first_slot_marks_the_start_and_a_short_period_waits_for_the_next() -> None:
    monday = moment(MOSCOW, 2026, 9, 21, 10, 0)
    week = 7 * 86400
    state = BotState(period_since=monday - 60)  # turned on at 09:59
    assert not report_due(state, monday - week, monday - 60)  # the slot it meets: marked only
    assert not report_due(state, monday, monday + 1)  # one minute is no week: skipped
    assert state.reported_slot == monday
    assert not report_due(state, monday, monday + 3600)  # a slot is reported once
    assert report_due(state, monday + week, monday + week + 1)  # a week and a minute


def test_a_period_closes_with_its_downtime_earnings_and_address_changes() -> None:
    start = NOW
    state = BotState(period_since=start, earnings_wei=str(1 * WEI), address_changes=2)
    state.downtime = {"dpn": 120.0}
    observe(state, uplink("tor", start + 100, alive=False), active=True)
    facts = ReportFacts(
        node=NodeState.ON,
        total_wei=str(int(3.5 * WEI)),
        exits=True,
        people=[PersonUse(name="anna", amount=5 * 1024**3)],
        watches_address=True,
    )
    report = close_period(state, start + 1000, start + 900, facts)
    assert report.downtime == {"dpn": 120.0, "tor": 900.0}  # tor is still silent: up to now
    assert report.earned_wei == str(int(2.5 * WEI)) and report.address_changes == 2
    assert (report.since, report.until) == (start, start + 1000)
    assert state.downtime == {} and state.address_changes == 0
    assert state.period_since == start + 1000 and state.reported_slot == start + 900
    assert state.earnings_wei == str(int(3.5 * WEI))
    # the next period counts only the silence after the report
    observe(state, uplink("tor", start + 1300, alive=True), active=True)
    assert state.downtime == {"tor": 300.0}


def test_the_report_tells_what_the_box_has_and_nothing_it_does_not() -> None:
    state = BotState(period_since=NOW)
    home = ReportFacts(
        node=NodeState.OFF,
        exits=True,
        people=[
            PersonUse(name="anna", amount=int(1.25 * 1024**3)),
            PersonUse(name="ivan", amount=3),
        ],
        watches_address=True,
    )
    lines = render_report(close_period(state, NOW + 86400, NOW, home), base_catalog(), UTC)
    assert lines.splitlines() == [
        "VibeDPN weekly report, 2026-09-21 to 2026-09-22",
        "Node: off.",
        "Exits: no outages.",
        "Access server: anna 1.2 GB, ivan 3 B.",
        "Changes of the public address: 0.",
    ]
    vps = ReportFacts(node=NodeState.SILENT, exits=False, people=None, watches_address=False)
    short = render_report(close_period(state, NOW + 2 * 86400, NOW, vps), base_catalog(), UTC)
    assert short.splitlines()[1:] == ["Node: did not answer."]


def test_the_first_report_of_a_node_has_its_total_only_and_speaks_russian() -> None:
    state = BotState(period_since=NOW)
    state.downtime = {"tor": 3700.0, "dpn": 40.0}
    facts = ReportFacts(
        node=NodeState.ON, total_wei=str(int(12.3456789 * WEI)), exits=True, watches_address=False
    )
    russian = load_catalog(LOCALES, "ru")
    lines = render_report(close_period(state, NOW + 600, NOW, facts), russian, MOSCOW)
    assert lines.splitlines() == [
        "Недельный отчёт VibeDPN, 21.09.2026 — 21.09.2026",
        "Нода: всего заработано 12,3456 MYST.",
        "Выходы молчали: tor 1 ч 1 мин, dpn 40 с.",
    ]


# --- sending ------------------------------------------------------------------------------------


def notice_at(at: float, name: str = "tor", reason: str = "") -> Notice:
    return Notice(
        at=at, kind=NoticeKind.DOWN, subject=Subject.UPLINK, name=name, since=at, reason=reason
    )


def test_notices_close_together_leave_as_one_message() -> None:
    state = BotState()
    enqueue(state, notice_at(NOW))
    enqueue(state, notice_at(NOW + 3, "dpn"))
    assert take_batch(state, NOW + MERGE_SECONDS - 1, text) is None
    batch = take_batch(state, NOW + MERGE_SECONDS, text)
    assert batch is not None
    count, message = batch
    assert count == 2 and message == (
        "Exit tor has not answered since 14:13.\n\nExit dpn has not answered since 14:13."
    )


def test_a_linked_chat_or_a_report_does_not_wait_and_a_pause_is_kept() -> None:
    state = BotState()
    enqueue(state, Notice(at=NOW, kind=NoticeKind.LINKED))
    assert take_batch(state, NOW, text) == (
        1,
        "This chat now gets the alerts and the weekly report of your VibeDPN box.",
    )
    failed(state, NOW, "Telegram: Too Many Requests: retry after 7", "via tor", retry_after=7)
    assert take_batch(state, NOW + 6, text) is None
    assert take_batch(state, NOW + 7, text) is not None


def test_a_message_never_grows_past_the_limit_of_telegram() -> None:
    state = BotState()
    for index in range(40):
        enqueue(state, notice_at(NOW, f"wg-{index}", "x" * 300))
    for index in range(40):
        state.outbox[index] = state.outbox[index].model_copy(update={"subject": Subject.DDNS})
    batch = take_batch(state, NOW + MERGE_SECONDS, text)
    assert batch is not None
    count, message = batch
    assert 0 < count < 40 and len(message) <= MESSAGE_CHARS


def test_a_failure_waits_longer_each_time_and_a_delivery_starts_over() -> None:
    state = BotState()
    enqueue(state, notice_at(NOW))
    pauses = []
    for _ in range(9):
        failed(state, NOW, "tor: ConnectionRefusedError", "via tor")
        pauses.append(state.delivery.retry_at - NOW)
    assert pauses[:4] == [5.0, 10.0, 20.0, 40.0] and pauses[-1] == MAX_BACKOFF_SECONDS
    assert state.delivery.last_ok is False and state.outbox  # the message stays
    delivered(state, 1, NOW + 400, "via tor")
    assert state.outbox == [] and state.delivery.failures == 0 and state.delivery.last_ok


def test_the_state_comes_back_from_its_file_and_a_broken_one_starts_afresh(tmp_path: Path) -> None:
    state = BotState(heartbeat=NOW)
    enqueue(state, notice_at(NOW))
    path = tmp_path / "telegram.json"
    path.write_text(state.model_dump_json(), encoding="utf-8")
    assert load_state(path) == state
    path.write_text("{ broken", encoding="utf-8")
    assert load_state(path) == BotState()


@pytest.mark.parametrize(
    ("notice", "russian"),
    [
        (
            Notice(at=NOW, kind=NoticeKind.DOWN, subject=Subject.UPLINK, name="tor", since=NOW),
            "Выход tor не отвечает с 17:13.",
        ),
        (
            Notice(
                at=NOW,
                kind=NoticeKind.BOX_BACK,
                since=NOW - 2 * 86400,
                until=NOW,
            ),
            "Коробка снова в сети: была выключена 2 дн, с 19.09.2026 17:13 до 17:13.",
        ),
    ],
)
def test_a_notice_speaks_the_language_of_the_box(notice: Notice, russian: str) -> None:
    assert render(notice, load_catalog(LOCALES, "ru"), MOSCOW, NOW) == russian
