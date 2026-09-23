"""Per-peer traffic: counting what is new, surviving a restart, and forgetting a peer that left."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from vibedpn.api.traffic import samples_of, watch_traffic
from vibedpn.engine.traffic import (
    Sample,
    advance,
    connect,
    day_of,
    forget,
    prune,
    record,
    totals,
)
from vibedpn.engine.wg import PeerLink

KEY = "AAAA1111bbbb2222CCCC3333dddd4444EEEE5555fff="
OTHER = "ZZZZ9999yyyy8888XXXX7777wwww6666VVVV5555uuu="


def moment(day: str, hour: int = 12) -> float:
    return (
        datetime.strptime(f"{day} {hour:02d}:00", "%Y-%m-%d %H:%M").replace(tzinfo=UTC).timestamp()
    )


def test_what_is_new_since_the_last_look() -> None:
    first = Sample(KEY, 1000, 2000)
    # never seen: the peer may have been running while core was not, so all of it is new
    assert advance(None, first) == (1000, 2000)
    # the usual case: the difference
    assert advance(first, Sample(KEY, 1500, 2500)) == (500, 500)
    # nothing moved
    assert advance(first, Sample(KEY, 1000, 2000)) == (0, 0)
    # the interface restarted and the counter starts again: what it shows now is all new traffic,
    # not a negative number and not a silent zero
    assert advance(first, Sample(KEY, 30, 40)) == (30, 40)


def test_totals_survive_a_restart_of_the_interface(tmp_path: Path) -> None:
    connection = connect(tmp_path)
    day = "2026-09-19"
    record(connection, [Sample(KEY, 1_000, 2_000)], moment(day, 10))
    record(connection, [Sample(KEY, 5_000, 6_000)], moment(day, 11))
    # the box restarts: wg starts counting from zero again
    record(connection, [Sample(KEY, 700, 300)], moment(day, 12))

    total = totals(connection)[0]
    assert (total.rx_bytes, total.tx_bytes) == (5_700, 6_300)
    assert total.total_bytes == 12_000


def test_totals_are_per_peer_and_per_period(tmp_path: Path) -> None:
    connection = connect(tmp_path)
    record(connection, [Sample(KEY, 100, 100), Sample(OTHER, 10, 10)], moment("2026-09-17"))
    record(connection, [Sample(KEY, 600, 600), Sample(OTHER, 20, 20)], moment("2026-09-19"))

    everything = {item.public_key: item.total_bytes for item in totals(connection)}
    assert everything == {KEY: 1_200, OTHER: 40}
    # the busiest peer comes first: that is the one a question about traffic is usually about
    assert totals(connection)[0].public_key == KEY

    since_today = {item.public_key: item.total_bytes for item in totals(connection, "2026-09-19")}
    assert since_today == {KEY: 1_000, OTHER: 20}


def test_a_peer_that_left_is_forgotten(tmp_path: Path) -> None:
    connection = connect(tmp_path)
    record(connection, [Sample(KEY, 100, 100), Sample(OTHER, 50, 50)], moment("2026-09-19"))
    forget(connection, KEY)
    assert [item.public_key for item in totals(connection)] == [OTHER]
    # and its last sample goes too, or a peer with the same key later would start in its debt
    record(connection, [Sample(KEY, 10, 10)], moment("2026-09-19"))
    assert {item.public_key: item.total_bytes for item in totals(connection)}[KEY] == 20


def test_old_days_are_pruned(tmp_path: Path) -> None:
    connection = connect(tmp_path)
    record(connection, [Sample(KEY, 100, 100)], moment("2023-01-01"))
    record(connection, [Sample(KEY, 300, 300)], moment("2026-09-19"))
    assert prune(connection, moment("2026-09-19"), days=30) == 1
    assert totals(connection)[0].total_bytes == 400


def test_the_day_of_a_sample_is_utc() -> None:
    assert day_of(moment("2026-09-19", hour=23)) == "2026-09-19"
    assert day_of(moment("2026-09-19", hour=0)) == "2026-09-19"


def test_the_watcher_adds_every_sample_and_keeps_going_after_a_bad_read(tmp_path: Path) -> None:
    """The watcher of core: it samples, it records, and a read it could not make is not the end of
    it — wg-server may be restarting, and the next sample carries what this one missed."""
    dumps: list[list[Sample] | None] = [
        samples_of({KEY: PeerLink("203.0.113.7:1", 0, 1_000, 500)}),
        None,  # the interface could not be read this time
        samples_of({KEY: PeerLink("203.0.113.7:1", 0, 1_500, 700)}),
    ]
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    asyncio.run(
        watch_traffic(
            tmp_path,
            read=lambda: dumps.pop(0) if dumps else None,
            sleep=sleep,
            now=lambda: moment("2026-09-19"),
            rounds=3,
        )
    )

    connection = connect(tmp_path)
    total = totals(connection)[0]
    assert (total.rx_bytes, total.tx_bytes) == (1_500, 700)
    assert len(slept) == 3 and slept[0] == 60.0
