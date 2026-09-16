"""The event journal: the store, hostapd's control socket, Wi-Fi and uplink watchers, the API."""

import asyncio
import shutil
import socket
import tempfile
import threading
from collections.abc import Iterator
from ipaddress import IPv4Address
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vibedpn.api.app import create_app
from vibedpn.api.models import EventView, WifiClientView
from vibedpn.api.uplink import watch_uplink
from vibedpn.api.wifi import to_event, watch_wifi
from vibedpn.config import Config, Upstream
from vibedpn.engine import events as events_module
from vibedpn.engine.devices import DeviceStore, Neighbour
from vibedpn.engine.events import (
    RETENTION_SECONDS,
    Event,
    EventAction,
    EventKind,
    EventStore,
)
from vibedpn.engine.hostapd import hostapd_conf
from vibedpn.engine.router import UPLINKS, Uplink
from vibedpn.engine.wifi import (
    ApEvent,
    HostapdControl,
    Station,
    WifiError,
    parse_event,
    parse_station,
)
from vibedpn.event_view import client_line, duration_text, event_line, event_text

from .conftest import home_config, vps_config
from .test_wifi import wifi_box

PHONE = "92:da:e8:fa:f8:63"
LAPTOP = "aa:bb:cc:dd:ee:01"
# `hostapd_cli all_sta` of hostapd 2.11 answers STA-FIRST with the MAC, then key=value lines
# (src/ap/ctrl_iface_ap.c).
STATION_REPLY = (
    f"{PHONE}\nflags=[AUTH][ASSOC][AUTHORIZED]\naid=1\nrx_packets=1200\ntx_packets=900\n"
    "rx_bytes=3664039\ntx_bytes=12411487\ninactive_msec=8536\nsignal=-56\nconnected_time=7432\n"
)


class StopLoopError(Exception):
    pass


# --- the store ---------------------------------------------------------------------------------


def test_events_come_back_newest_first_and_filter_by_kind_and_time(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.db")
    store.add(Event(100.0, EventKind.WIFI, PHONE, EventAction.CLIENT_CONNECTED))
    store.add(Event(200.0, EventKind.UPLINK, "dpn", EventAction.GATEWAY_SILENT))
    store.add(
        Event(
            300.0, EventKind.WIFI, PHONE, EventAction.CLIENT_DISCONNECTED, {"session_seconds": 200}
        )
    )
    found = store.events()
    assert [item.time for item in found] == [300.0, 200.0, 100.0]
    assert found[0].detail == {"session_seconds": 200}
    assert [item.kind for item in store.events(kind=EventKind.UPLINK)] == [EventKind.UPLINK]
    assert [item.time for item in store.events(since=150.0)] == [300.0, 200.0]
    assert len(store.events(limit=1)) == 1


def test_old_and_surplus_events_are_dropped_on_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = EventStore(tmp_path / "events.db")
    store.add(Event(0.0, EventKind.WIFI, PHONE, EventAction.CLIENT_CONNECTED))
    store.add(Event(RETENTION_SECONDS + 10.0, EventKind.WIFI, PHONE, EventAction.CLIENT_CONNECTED))
    assert [item.time for item in store.events()] == [RETENTION_SECONDS + 10.0]

    monkeypatch.setattr(events_module, "MAX_EVENTS", 3)
    base = RETENTION_SECONDS + 20.0
    for step in range(5):
        store.add(Event(base + step, EventKind.WIFI, PHONE, EventAction.CLIENT_CONNECTED))
    assert [item.time for item in store.events()] == [base + 4, base + 3, base + 2]


# --- parsing what hostapd says -----------------------------------------------------------------


def test_events_of_clients_and_of_the_access_point_are_recognised() -> None:
    assert parse_event(f"<3>AP-STA-CONNECTED {PHONE}") == ApEvent("AP-STA-CONNECTED", PHONE)
    assert parse_event(f"<3>AP-STA-DISCONNECTED {PHONE.upper()}\n") == ApEvent(
        "AP-STA-DISCONNECTED", PHONE
    )
    assert parse_event("<3>AP-ENABLED ") == ApEvent("AP-ENABLED", None)
    assert parse_event("<3>AP-DISABLED") == ApEvent("AP-DISABLED", None)
    # everything else hostapd reports stays out of the journal
    assert parse_event(f"<3>EAPOL-4WAY-HS-COMPLETED {PHONE}") is None
    assert parse_event("<3>AP-STA-CONNECTED not-a-mac") is None
    assert parse_event("OK") is None


def test_a_station_reply_gives_the_numbers_the_panel_shows() -> None:
    assert parse_station(STATION_REPLY) == Station(
        mac=PHONE,
        connected_seconds=7432,
        signal_dbm=-56,
        inactive_ms=8536,
        rx_bytes=3664039,
        tx_bytes=12411487,
    )
    assert parse_station("") is None
    assert parse_station("FAIL\n") is None
    with pytest.raises(WifiError, match="not a station"):
        parse_station("UNKNOWN COMMAND\n")


# --- the control socket, against a fake hostapd on a real UNIX datagram socket -----------------


class FakeHostapd:
    """Answers commands the way hostapd does and pushes events to the attached client."""

    def __init__(self, directory: Path, stations: list[str]) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.sock.bind(str(directory / "wlan0"))
        self.sock.settimeout(0.1)
        self.stations = stations
        self.client: str | None = None
        self.running = True
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _reply(self, command: str) -> str:
        if command == "ATTACH":
            return "OK\n"
        if command == "PING":
            return "PONG\n"
        if command == "STA-FIRST":
            return self.stations[0] if self.stations else ""
        if command.startswith("STA-NEXT "):
            macs = [item.splitlines()[0] for item in self.stations]
            index = macs.index(command.split()[1]) + 1
            return self.stations[index] if index < len(self.stations) else ""
        return "UNKNOWN COMMAND\n"

    def _serve(self) -> None:
        while self.running:
            try:
                data, address = self.sock.recvfrom(4096)
            except TimeoutError:
                continue
            except OSError:
                return
            command = data.decode()
            if command == "ATTACH":
                self.client = address
            self.sock.sendto(self._reply(command).encode(), address)

    def push(self, message: str) -> None:
        assert self.client is not None
        self.sock.sendto(message.encode(), self.client)

    def close(self) -> None:
        self.running = False
        self.thread.join()
        self.sock.close()


@pytest.fixture
def short_dir() -> Iterator[Path]:
    # A UNIX socket path is limited to about 104 bytes: pytest's tmp_path on macOS is longer.
    directory = Path(tempfile.mkdtemp(prefix="vdpn", dir="/tmp"))
    yield directory
    shutil.rmtree(directory, ignore_errors=True)


def test_the_client_attaches_lists_stations_and_receives_events(short_dir: Path) -> None:
    laptop_reply = STATION_REPLY.replace(PHONE, LAPTOP).replace("signal=-56", "signal=-70")
    hostapd = FakeHostapd(short_dir, [STATION_REPLY, laptop_reply])
    try:
        with HostapdControl("wlan0", short_dir) as control:
            control.attach()
            assert [item.mac for item in control.stations()] == [PHONE, LAPTOP]
            assert control.receive(0.2) is None  # nothing happened yet
            hostapd.push(f"<3>AP-STA-DISCONNECTED {LAPTOP}")
            assert control.receive(1.0) == f"<3>AP-STA-DISCONNECTED {LAPTOP}"
            # an event arriving while a command waits for its reply is not taken for the reply
            hostapd.push(f"<3>AP-STA-CONNECTED {LAPTOP}")
            assert control.request("PING") == "PONG\n"
            local = control.local
        assert not local.exists()  # the client removes its own socket
    finally:
        hostapd.close()


def test_a_missing_access_point_is_a_readable_error(short_dir: Path) -> None:
    with pytest.raises(WifiError, match="cannot reach the access point"):
        HostapdControl("wlan0", short_dir)


# --- from hostapd events to the journal --------------------------------------------------------


def test_a_session_is_measured_from_its_connect() -> None:
    sessions: dict[str, float] = {}
    joined = to_event(ApEvent("AP-STA-CONNECTED", PHONE), "wlan0", 1000.0, sessions)
    assert joined == Event(1000.0, EventKind.WIFI, PHONE, EventAction.CLIENT_CONNECTED)
    left = to_event(ApEvent("AP-STA-DISCONNECTED", PHONE), "wlan0", 1600.0, sessions)
    assert left.detail == {"session_seconds": 600}
    # a client nobody saw arrive leaves without a length rather than with a wrong one
    unknown = to_event(ApEvent("AP-STA-DISCONNECTED", LAPTOP), "wlan0", 1700.0, sessions)
    assert unknown.detail == {}
    sessions[PHONE] = 1800.0
    down = to_event(ApEvent("AP-DISABLED", None), "wlan0", 1900.0, sessions)
    assert down == Event(1900.0, EventKind.WIFI, "wlan0", EventAction.AP_DISABLED)
    assert sessions == {}  # the access point went down: no session survives it


class FakeControl:
    def __init__(self, messages: list[str | None], stations: list[Station]) -> None:
        self.messages = messages
        self.present = stations
        self.pings = 0
        self.closed = False

    def attach(self) -> None:
        return None

    def stations(self) -> list[Station]:
        return self.present

    def receive(self, timeout: float) -> str | None:
        if not self.messages:
            raise WifiError("lost the access point: gone")
        return self.messages.pop(0)

    def request(self, command: str) -> str:
        assert command == "PING"
        self.pings += 1
        return "PONG\n"

    def close(self) -> None:
        self.closed = True


def test_the_wifi_watcher_journals_sessions_including_the_ones_already_running(
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = Config.model_validate(wifi_box())
    phone = Station(PHONE, 300, -56, 100, 1, 1)  # connected 300 s before the watcher attached
    control = FakeControl(
        [None, f"<3>AP-STA-DISCONNECTED {PHONE}", f"<3>AP-STA-CONNECTED {LAPTOP}", "<3>OTHER"],
        [phone],
    )
    times = iter([1000.0, 1100.0, 1200.0])
    journaled: list[Event] = []

    async def stop(_seconds: float) -> None:
        raise StopLoopError

    with pytest.raises(StopLoopError):
        asyncio.run(
            watch_wifi(
                config,
                journaled.append,
                open_control=lambda _interface: control,
                sleep=stop,
                clock=lambda: next(times),
            )
        )
    assert journaled == [
        Event(
            1100.0, EventKind.WIFI, PHONE, EventAction.CLIENT_DISCONNECTED, {"session_seconds": 400}
        ),
        Event(1200.0, EventKind.WIFI, LAPTOP, EventAction.CLIENT_CONNECTED),
    ]
    assert control.pings == 1  # the quiet spell was checked, not trusted
    assert control.closed
    assert "lost the access point" in capsys.readouterr().err


def test_a_box_without_wifi_has_no_wifi_watcher() -> None:
    config = Config.model_validate(home_config())

    def never(_interface: str) -> FakeControl:
        raise AssertionError("no access point to attach to")

    asyncio.run(watch_wifi(config, lambda _event: None, open_control=never))


def test_the_uplink_watcher_journals_changes_only() -> None:
    answers = [True, True, False, False, True]
    journaled: list[Event] = []

    def fake_probe(_address: str, _timeout: float) -> bool:
        return answers.pop(0)

    def fake_apply(_uplink: Uplink, _alive: bool) -> None:
        return None

    async def fake_sleep(_seconds: float) -> None:
        if not answers:
            raise StopLoopError

    with pytest.raises(StopLoopError):
        asyncio.run(
            watch_uplink(
                "vps",
                UPLINKS[Upstream.VPS],
                probe=fake_probe,
                apply=fake_apply,
                sleep=fake_sleep,
                journal=journaled.append,
            )
        )
    assert [(item.subject, item.action) for item in journaled] == [
        ("vps", EventAction.GATEWAY_ANSWERS),
        ("vps", EventAction.GATEWAY_SILENT),
        ("vps", EventAction.GATEWAY_ANSWERS),
    ]


def test_hostapd_is_configured_with_the_control_socket_core_reads() -> None:
    conf = hostapd_conf(Config.model_validate(wifi_box()), "passphrase-12")
    assert conf is not None
    assert "ctrl_interface=/var/run/hostapd\n" in conf
    assert "ctrl_interface_group=0\n" in conf


# --- the API ------------------------------------------------------------------------------------


def test_the_journal_and_the_clients_through_the_api(tmp_path: Path) -> None:
    config = Config.model_validate(wifi_box())
    store = EventStore(tmp_path / "events.db")
    store.add(Event(100.0, EventKind.WIFI, PHONE, EventAction.CLIENT_CONNECTED))
    store.add(Event(200.0, EventKind.UPLINK, "dpn", EventAction.GATEWAY_ANSWERS))
    devices = DeviceStore(tmp_path / "devices.db")
    devices.record([Neighbour(PHONE, IPv4Address("192.168.50.20"))], 50.0, lambda _address: "phone")

    def stations(interface: str) -> list[Station]:
        assert interface == "wlan0"
        return [parse_station(STATION_REPLY)]  # type: ignore[list-item]

    client = TestClient(
        create_app(config, events=store, device_store=devices, wifi_stations=stations)
    )
    listed = [EventView.model_validate(item) for item in client.get("/events").json()]
    assert [item.action for item in listed] == ["gateway_answers", "client_connected"]
    wifi_only = client.get("/events", params={"kind": "wifi", "since": 50}).json()
    assert [item["subject"] for item in wifi_only] == [PHONE]
    assert client.get("/events", params={"kind": "tor"}).status_code == 422

    (phone,) = [WifiClientView.model_validate(item) for item in client.get("/wifi/clients").json()]
    assert (phone.name, phone.connected_seconds, phone.signal_dbm) == ("phone", 7432, -56)


def test_the_api_says_why_there_is_nothing_to_show(tmp_path: Path) -> None:
    vps = TestClient(create_app(Config.model_validate(vps_config())))
    assert vps.get("/events").status_code == 404
    assert vps.get("/wifi/clients").status_code == 404

    def unreachable(_interface: str) -> list[Station]:
        raise WifiError("cannot reach the access point at /run/vibedpn/hostapd/wlan0")

    box = TestClient(
        create_app(
            Config.model_validate(wifi_box()),
            events=EventStore(tmp_path / "events.db"),
            wifi_stations=unreachable,
        )
    )
    answer = box.get("/wifi/clients")
    assert answer.status_code == 503
    assert "cannot reach the access point" in answer.json()["detail"]


# --- the terminal ------------------------------------------------------------------------------


def test_durations_keep_the_two_units_that_matter() -> None:
    assert duration_text(40) == "40 s"
    assert duration_text(420) == "7 min"
    assert duration_text(54572) == "15 h 9 min"
    assert duration_text(3 * 86400 + 4 * 3600 + 59) == "3 d 4 h"


def test_the_cli_builds_its_own_phrases_from_codes() -> None:
    left = EventView(
        time=0.0,
        kind="wifi",
        subject=PHONE,
        action="client_disconnected",
        detail={"session_seconds": 600},
    )
    assert event_text(left) == f"{PHONE} left Wi-Fi after 10 min"
    silent = EventView(time=0.0, kind="uplink", subject="dpn", action="gateway_silent", detail={})
    assert event_text(silent) == "uplink dpn: the gateway does not answer"
    assert event_line(silent).endswith("uplink dpn: the gateway does not answer")
    phone = WifiClientView(
        mac=PHONE,
        name="phone",
        connected_seconds=54572,
        signal_dbm=-56,
        inactive_ms=None,
        rx_bytes=None,
        tx_bytes=None,
    )
    assert client_line(phone) == f"phone ({PHONE})  connected 15 h 9 min, -56 dBm"
