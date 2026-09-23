"""Uplink watcher and the ICMP probe: pure packet code, and route changes only on a new answer."""

import asyncio
import struct

import pytest

from vibedpn.api import background
from vibedpn.api.uplink import Report, UplinkState, UplinkWatchers, watch_uplink
from vibedpn.config import Upstream
from vibedpn.engine import probe
from vibedpn.engine.router import UPLINKS, RouterError, Uplink


def test_echo_request_carries_a_valid_checksum() -> None:
    packet = probe.echo_request(0x1234, 7)
    assert packet[0] == probe.ICMP_ECHO_REQUEST
    # The Internet checksum over a packet that already contains its checksum is zero.
    assert probe.checksum(packet) == 0


def test_echo_reply_is_matched_behind_the_ip_header() -> None:
    icmp = struct.pack("!BBHHH", probe.ICMP_ECHO_REPLY, 0, 0, 0x1234, 7) + probe.PAYLOAD
    ip_header = bytes([0x45]) + bytes(19)  # IHL 5: 20 bytes
    assert probe.is_echo_reply(ip_header + icmp, 0x1234, 7)
    assert not probe.is_echo_reply(ip_header + icmp, 0x1234, 8)
    request = struct.pack("!BBHHH", probe.ICMP_ECHO_REQUEST, 0, 0, 0x1234, 7)
    assert not probe.is_echo_reply(ip_header + request, 0x1234, 7)
    assert not probe.is_echo_reply(ip_header[:10], 0x1234, 7)
    assert not probe.is_echo_reply(b"", 0x1234, 7)


class StopWatcherError(Exception):
    pass


def run_watcher(answers: list[bool | OSError], failing_applies: int = 0) -> list[tuple[str, bool]]:
    applied: list[tuple[str, bool]] = []
    remaining = list(answers)
    failures = [failing_applies]

    def fake_probe(address: str, _timeout: float) -> bool:
        assert address == "10.77.0.10"
        answer = remaining.pop(0)
        if isinstance(answer, OSError):
            raise answer
        return answer

    def fake_apply(uplink: Uplink, alive: bool) -> None:
        if failures[0]:
            failures[0] -= 1
            raise RouterError("ip route replace failed")
        applied.append(("vps" if uplink == UPLINKS[Upstream.VPS] else uplink.gateway, alive))

    async def fake_sleep(_seconds: float) -> None:
        if not remaining:
            raise StopWatcherError

    with pytest.raises(StopWatcherError):
        asyncio.run(
            watch_uplink(
                "vps", UPLINKS[Upstream.VPS], probe=fake_probe, apply=fake_apply, sleep=fake_sleep
            )
        )
    return applied


def test_watcher_sets_the_route_on_every_round() -> None:
    """A route removed behind the watcher's back comes back on the next round."""
    assert run_watcher([True, True, False, False, True]) == [
        ("vps", True),
        ("vps", True),
        ("vps", False),
        ("vps", False),
        ("vps", True),
    ]


def test_watcher_logs_only_changes(capsys: pytest.CaptureFixture[str]) -> None:
    run_watcher([True, True, True, False])
    err = capsys.readouterr().err
    assert err.count("answers; LAN traffic goes through it") == 1
    assert err.count("does not answer") == 1


def test_watcher_starts_by_withdrawing_a_route_of_a_silent_gateway() -> None:
    """A route left from an earlier run must not survive a gateway that never answered."""
    assert run_watcher([False]) == [("vps", False)]


def test_watcher_retries_a_failed_route_change_and_treats_probe_errors_as_dead() -> None:
    assert run_watcher([True, True], failing_applies=1) == [("vps", True)]
    assert run_watcher([OSError(1, "Operation not permitted"), True]) == [
        ("vps", False),
        ("vps", True),
    ]


def test_an_uplink_watcher_that_raises_is_started_again(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A dead watcher leaves the route of its gateway to nobody: a gateway that goes quiet later
    would keep its route, and the LAN traffic would sink into it."""
    monkeypatch.setattr(background, "FIRST_PAUSE_SECONDS", 0.0)
    started: list[str] = []

    async def watch(key: str, _uplink: Uplink, report: Report) -> None:
        started.append(key)
        if len(started) == 1:
            raise RuntimeError("the first round fails")
        report(UplinkState(True, 1.0))
        await asyncio.Event().wait()

    async def scenario() -> None:
        watchers = UplinkWatchers({"vps": UPLINKS[Upstream.VPS]}, watch=watch)
        runner = asyncio.ensure_future(watchers.run())
        await asyncio.sleep(0.01)
        assert watchers.watched() == ["vps"]
        assert watchers.states()["vps"].alive
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)

    asyncio.run(scenario())
    assert started == ["vps", "vps"]
    log = capsys.readouterr().err
    assert "vibedpn-core: uplink vps watcher failed: RuntimeError at test_uplink.py:" in log


def test_watchers_started_again_start_every_watcher_anew() -> None:
    """The supervisor starts ``run`` again after a failure: the watchers it cancelled on its way
    out must not pass for running ones."""
    started: list[str] = []

    async def watch(key: str, _uplink: Uplink, _report: Report) -> None:
        started.append(key)
        await asyncio.Event().wait()

    async def scenario() -> None:
        watchers = UplinkWatchers({"vps": UPLINKS[Upstream.VPS]}, watch=watch)
        for _ in range(2):
            runner = asyncio.ensure_future(watchers.run())
            await asyncio.sleep(0.01)
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)

    asyncio.run(scenario())
    assert started == ["vps", "vps"]
