"""The supervisor of the background loops of core: a loop that raised is logged by its class and
place and started again after a growing pause; a loop that returned stays finished."""

import asyncio

import pytest

from vibedpn.api.background import (
    FIRST_PAUSE_SECONDS,
    LONGEST_PAUSE_SECONDS,
    STEADY_SECONDS,
    supervised,
)

SECRET = "123456:the-token-a-request-quoted"


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Pauses:
    """The sleep of the supervisor: it keeps every pause and lets no time pass."""

    def __init__(self) -> None:
        self.taken: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.taken.append(seconds)


def test_a_loop_that_raises_is_logged_and_started_again_after_a_growing_pause(
    capsys: pytest.CaptureFixture[str],
) -> None:
    starts: list[int] = []

    async def flaky() -> None:
        starts.append(len(starts))
        if len(starts) <= 3:
            raise RuntimeError(f"the request quoted {SECRET}")

    pauses = Pauses()
    asyncio.run(supervised("flaky", flaky, sleep=pauses, clock=Clock()))
    assert len(starts) == 4  # three failures, then it finished its work
    assert pauses.taken == [FIRST_PAUSE_SECONDS, 2 * FIRST_PAUSE_SECONDS, 4 * FIRST_PAUSE_SECONDS]
    log = capsys.readouterr().err
    assert log.count("vibedpn-core: flaky failed: RuntimeError at test_background.py:") == 3
    assert f"it starts again in {FIRST_PAUSE_SECONDS:g} s" in log
    assert SECRET not in log


def test_the_pause_stops_growing_at_its_bound() -> None:
    starts: list[int] = []

    async def broken() -> None:
        starts.append(len(starts))
        if len(starts) <= 12:
            raise OSError("no such device")

    pauses = Pauses()
    asyncio.run(supervised("broken", broken, sleep=pauses, clock=Clock()))
    assert len(pauses.taken) == 12
    assert pauses.taken == sorted(pauses.taken)
    assert pauses.taken[-3:] == [LONGEST_PAUSE_SECONDS] * 3


def test_a_loop_that_ran_steadily_before_it_raised_gets_a_short_pause_again() -> None:
    clock = Clock()
    starts: list[int] = []

    async def seldom() -> None:
        starts.append(len(starts))
        if len(starts) == 3:
            clock.now += STEADY_SECONDS  # this run worked for a while before it raised
        if len(starts) <= 4:
            raise RuntimeError("again")

    pauses = Pauses()
    asyncio.run(supervised("seldom", seldom, sleep=pauses, clock=clock))
    first, second = FIRST_PAUSE_SECONDS, 2 * FIRST_PAUSE_SECONDS
    assert pauses.taken == [first, second, first, second]


def test_a_loop_that_returns_is_not_started_again(capsys: pytest.CaptureFixture[str]) -> None:
    starts: list[int] = []

    async def finished() -> None:  # the Wi-Fi journal of a box without Wi-Fi
        starts.append(len(starts))

    pauses = Pauses()
    asyncio.run(supervised("finished", finished, sleep=pauses, clock=Clock()))
    assert starts == [0]
    assert pauses.taken == []
    assert capsys.readouterr().err == ""


def test_cancelling_ends_the_loop_while_it_runs_and_while_it_waits(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Shutdown cancels the tasks: that is no failure, and nothing starts again."""
    starts: list[str] = []

    async def forever() -> None:
        starts.append("forever")
        await asyncio.Event().wait()

    async def broken() -> None:
        starts.append("broken")
        raise RuntimeError("down")

    async def cancelled(name: str, start: object) -> None:
        assert callable(start)
        task = asyncio.create_task(supervised(name, start))  # the real sleep: a 5 s pause
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    async def scenario() -> None:
        await cancelled("forever", forever)
        await cancelled("broken", broken)

    asyncio.run(scenario())
    assert starts == ["forever", "broken"]
    log = capsys.readouterr().err
    assert "forever" not in log
    assert log.count("broken failed") == 1
