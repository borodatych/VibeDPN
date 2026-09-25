"""ASGI application factory: health, provider statistics (Stage 2) and tunnel peers (Stage 3)."""

import io
import sys
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import segno
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, ValidationError

from vibedpn import __version__
from vibedpn.api.consumer import ConsumerStatus
from vibedpn.api.lists import ListsStatus
from vibedpn.api.models import (
    AccessLink,
    AccessPerson,
    AccessPersonCreate,
    AccessUpdate,
    AccessView,
    ApplyView,
    BoxStatus,
    ConfigRereadView,
    DdnsUpdate,
    DdnsView,
    DevicePolicyUpdate,
    DevicePolicyView,
    DeviceView,
    DomainListUpdate,
    DomainListView,
    DomainRuleUpdate,
    DomainRuleView,
    DpnCountry,
    DpnCountryUpdate,
    DpnCountryView,
    DpnRegistrationResult,
    DpnRegistrationView,
    DpnStatus,
    EventView,
    HostInterface,
    JournalDeviceView,
    JournalEntryView,
    LearnedView,
    NetworkRuleUpdate,
    NetworkRuleView,
    NetworkUpdate,
    NetworkView,
    PeerCreate,
    PeerFile,
    PeerTraffic,
    PeerView,
    RoutingUpdate,
    RoutingView,
    TelegramReportView,
    TelegramToken,
    TelegramUpdate,
    TelegramView,
    TorUplinkUpdate,
    TorUplinkView,
    UpdateResultView,
    UpdateView,
    UplinkStatus,
    VpsLanAccessUpdate,
    VpsLanAccessView,
    WgUplinkCreate,
    WgUplinksView,
    WgUplinkView,
    WifiClientView,
    XrayUplinkUpdate,
    XrayUplinkView,
)
from vibedpn.api.smart import SmartLoop
from vibedpn.api.state import BoxState
from vibedpn.api.telegram import TelegramBot, link_url
from vibedpn.api.traffic import ACCESS_TRAFFIC_DIR
from vibedpn.api.uplink import UplinkWatchers
from vibedpn.atomic import write_private
from vibedpn.bootstrap import (
    SECRET_DIR_MODE,
    XRAY_LINK_FILE,
    BootstrapError,
    check_peer_text,
    network_for,
    wg_uplink_file,
)
from vibedpn.config import (
    WG_UPLINK_NAME,
    Config,
    ConfigError,
    DeviceConfig,
    DomainList,
    DomainRule,
    NetworkMode,
    NetworkRule,
    RoutingMode,
    Upstream,
)
from vibedpn.config_edit import (
    ConfigEditError,
    DeviceIdent,
    DeviceNotFoundError,
    ListNotFoundError,
    NetworkRuleNotFoundError,
    RuleNotFoundError,
    WgUplinkNotFoundError,
    remove_domain_list,
    remove_domain_rule,
    remove_network_rule,
    remove_wg_uplink,
    set_access,
    set_ddns,
    set_device,
    set_domain_list,
    set_domain_rule,
    set_dpn_country,
    set_network,
    set_network_rule,
    set_routing,
    set_telegram,
    set_tor_uplink,
    set_vps_lan_access,
    set_wg_uplink,
    set_xray_uplink,
    unset_device,
)
from vibedpn.detect import DetectError, HostProbe, Interface
from vibedpn.engine.access import (
    AccessError,
    PersonNameError,
    PersonNotFoundError,
    add_person,
    ensure_access,
    list_people,
    person_link,
    remove_person,
)
from vibedpn.engine.adguard import AdguardError, close_upstream_connections, set_dns_mode
from vibedpn.engine.apply import ApplyError, apply_state, request_apply
from vibedpn.engine.consumer import (
    CONSUMER_TEQUILAPI,
    CONSUMER_TIMEOUT_SECONDS,
    REGISTERED,
    ConsumerState,
    CountryOffer,
    countries,
    existing_identity,
    register,
    registration_offer,
)
from vibedpn.engine.ddns import STATE_FILE as DDNS_STATE_FILE
from vibedpn.engine.ddns import DdnsError
from vibedpn.engine.ddns import host_of as ddns_host
from vibedpn.engine.ddns import load_state as load_ddns_state
from vibedpn.engine.ddns import load_url as load_ddns_url
from vibedpn.engine.ddns import save_url as save_ddns_url
from vibedpn.engine.devices import DeviceError, DeviceStore, SeenDevice
from vibedpn.engine.events import DEFAULT_LIMIT, Event, EventError, EventKind, EventStore
from vibedpn.engine.learned import LearnedError
from vibedpn.engine.myst import MystError, ProviderStats, TequilaClient, provider_stats
from vibedpn.engine.router import (
    ACCESS_UID,
    COUNTRY_KEY_PREFIX,
    RouterError,
    RoutingFacts,
    dns_uplink,
    read_routing,
    uplink_table,
    used_uplinks,
)
from vibedpn.engine.sockdiag import Exchange, SockDiagError, netlink_exchange
from vibedpn.engine.telegram import TelegramError, check_token
from vibedpn.engine.traffic import connect as traffic_connect
from vibedpn.engine.traffic import forget as traffic_forget
from vibedpn.engine.traffic import totals as traffic_totals
from vibedpn.engine.update import read_revision, request_update, update_state
from vibedpn.engine.wg import (
    Peer,
    PeerExistsError,
    PeerLink,
    PeerNameError,
    PeerNotFoundError,
    SubnetFullError,
    WgError,
    add_peer,
    find_peer,
    list_peers,
    peer_config,
    read_wg_dump,
    remove_peer,
)
from vibedpn.engine.wifi import HostapdControl, Station, WifiError
from vibedpn.engine.xray import XrayError, parse_share_link

StatsSource = Callable[[], ProviderStats]
RoutingReader = Callable[[Config], RoutingFacts]
# Tells the running AdGuard the DNS mode; None: no AdGuard on this box.
DnsModeSetter = Callable[[Config, bool], bool | None]  # the box, did smart come or go
# Drops the connections AdGuard opened along the uplink its queries no longer take
DnsReconnect = Callable[[Config], None]
AdguardFollows = Literal["applied", "pending", "none"]
# The before and the after of a live change: what AdGuard makes of it
DnsFollower = Callable[[Config, Config], AdguardFollows]
NO_LAN = "this box routes no LAN"
DpnOffers = Callable[[], list[CountryOffer]]
LinkSource = Callable[[], dict[str, PeerLink] | None]
NO_TUNNEL = "this box runs no WireGuard server"
# The peer errors a caller can act on, and the HTTP status each one maps to.
PEER_ERROR_STATUS: tuple[tuple[type[WgError], int], ...] = (
    (PeerNotFoundError, 404),
    (PeerExistsError, 409),
    (SubnetFullError, 409),
    (PeerNameError, 422),
)


class Health(BaseModel):
    """Liveness answer used by the container healthcheck."""

    status: Literal["ok"]
    version: str


def _default_stats() -> ProviderStats:
    client = TequilaClient()
    try:
        return provider_stats(client)
    finally:
        client.close()


def _http_error(exc: WgError) -> HTTPException:
    for kind, status in PEER_ERROR_STATUS:
        if isinstance(exc, kind):
            return HTTPException(status_code=status, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _view(peer: Peer, links: dict[str, PeerLink] | None) -> PeerView:
    link = None if links is None else links.get(peer.public_key)
    return PeerView(
        name=peer.name,
        address=peer.address,
        public_key=peer.public_key,
        created=peer.created,
        endpoint=None if link is None else link.endpoint,
        latest_handshake=None if link is None else link.latest_handshake,
        rx_bytes=None if link is None else link.rx_bytes,
        tx_bytes=None if link is None else link.tx_bytes,
        applied=None if links is None else link is not None,
        tunnel_only=peer.tunnel_only,
    )


def _device_view(seen: SeenDevice, configured: list[DeviceConfig]) -> DeviceView:
    """config.yaml names a device by MAC first, by address second."""
    own = next((item for item in configured if item.mac == seen.mac), None) or next(
        (item for item in configured if item.mac is None and item.ip == seen.ip), None
    )
    return DeviceView(
        mac=seen.mac,
        ip=seen.ip,
        name=None if own is None else own.name,
        hostname=seen.hostname,
        policy=None if own is None else own.policy.value,
        seen=True,
        first_seen=datetime.fromtimestamp(seen.first_seen, tz=UTC),
        last_seen=datetime.fromtimestamp(seen.last_seen, tz=UTC),
    )


def _unseen_views(seen: list[SeenDevice], configured: list[DeviceConfig]) -> list[DeviceView]:
    """Devices with a policy in config.yaml that discovery has not met: without them a policy
    set by address before the device ever showed up could not be seen or removed."""
    macs = {item.mac for item in seen}
    ips = {item.ip for item in seen}
    return [
        DeviceView(
            mac=item.mac,
            ip=item.ip,
            name=item.name,
            hostname=None,
            policy=item.policy.value,
            seen=False,
            first_seen=None,
            last_seen=None,
        )
        for item in configured
        if (item.mac is not None and item.mac not in macs)
        or (item.mac is None and item.ip not in ips)
    ]


MAX_EVENT_LIMIT = 5000
NO_JOURNAL = "this box keeps no event journal: it routes no LAN"
NO_ACCESS_POINT = "this box runs no access point (network.wifi)"

WifiStations = Callable[[str], list[Station]]


def read_stations(interface: str) -> list[Station]:
    """The clients of the access point now, asked over its control socket."""
    with HostapdControl(interface) as control:
        return control.stations()


def device_names(box: Config | None, device_store: DeviceStore | None) -> dict[str, str]:
    """A name for each MAC the box knows: the owner's name in config.yaml first, then the name the
    device gave itself (DHCP or reverse DNS). A device that gave none has no entry: the reader shows
    it as unknown, next to its MAC."""
    names: dict[str, str] = {}
    if device_store is not None:
        try:
            names = {seen.mac: seen.hostname for seen in device_store.devices() if seen.hostname}
        except DeviceError:
            names = {}
    if box is not None:
        names.update({device.mac: device.name for device in box.devices if device.mac})
    return names


@dataclass(frozen=True)
class LinkRouteSources:
    """What the routes about the links of the box read: devices, the journal, the access point,
    and the secrets and data directory core shares with the host."""

    device_store: DeviceStore | None
    events: EventStore | None
    wifi_stations: WifiStations
    secrets_dir: Path | None
    data_dir: Path | None


def _add_link_routes(
    application: FastAPI,
    current: Callable[[], Config | None],
    state: BoxState | None,
    sources: LinkRouteSources,
) -> None:
    """The journal and the Wi-Fi clients, and the WireGuard exits added in the panel."""
    _add_event_routes(
        application, current, sources.events, sources.device_store, sources.wifi_stations
    )
    _add_wg_uplink_routes(application, current, state, sources.secrets_dir, sources.data_dir)
    _add_xray_uplink_routes(application, current, state, sources.secrets_dir, sources.data_dir)
    _add_tor_uplink_routes(application, current, state, sources.data_dir)


NO_PANEL_APPLY = "this box takes no WireGuard exits from the panel: it routes no LAN"
NO_UPDATE_FILES = "this core keeps no data directory: the host cannot be asked to update"


def _update_view(data: Path) -> UpdateView:
    revision = read_revision(data)
    progress = update_state(data, time.time())
    last = progress.last
    return UpdateView(
        branch=revision.branch if revision else None,
        commit=revision.commit if revision else None,
        committed_at=revision.committed_at if revision else None,
        pending=progress.pending,
        last=None
        if last is None
        else UpdateResultView(
            ok=last.ok,
            message=last.message,
            before=last.before,
            after=last.after,
            finished_at=last.finished_at,
        ),
    )


def _add_update_routes(application: FastAPI, data_dir: Path | None) -> None:
    """``/update``: the box updates itself when the panel asks; the host runs it (decision 26)"""

    def data() -> Path:
        if data_dir is None:
            raise HTTPException(status_code=404, detail=NO_UPDATE_FILES)
        return data_dir

    @application.get("/update", response_model=UpdateView)
    def get_update() -> UpdateView:
        return _update_view(data())

    @application.post("/update", response_model=UpdateView)
    def post_update() -> UpdateView:
        where = data()
        if update_state(where, time.time()).pending:
            raise HTTPException(status_code=409, detail="an update is already running")
        try:
            request_update(where, time.time())
        except ApplyError as exc:
            raise HTTPException(status_code=503, detail=f"the host was not asked: {exc}") from exc
        return _update_view(where)


def _apply_view(data: Path) -> ApplyView:
    """The last change the host applied for the panel, and whether one is still waiting."""
    progress = apply_state(data, time.time())
    last = progress.last
    return ApplyView(
        pending=progress.pending,
        ok=None if last is None else last.ok,
        message="" if last is None else last.message,
        finished_at=None if last is None else last.finished_at,
    )


def _ask_host(data: Path, reason: str) -> None:
    """Leave the request the host's path unit picks up: core cannot start containers itself."""
    try:
        request_apply(data, time.time(), reason)
    except ApplyError as exc:
        raise HTTPException(
            status_code=503, detail=f"saved, but the host was not asked to apply it: {exc}"
        ) from exc


def _add_tor_uplink_routes(
    application: FastAPI,
    current: Callable[[], Config | None],
    state: BoxState | None,
    data_dir: Path | None,
) -> None:
    """``/uplinks/tor``: the free exit through Tor turned on and off in the panel (decision 27);
    the host starts or stops its gateway when it applies the request core leaves."""

    def box_paths() -> tuple[Config, BoxState, Path]:
        box = current()
        if box is None or box.network is None or state is None or data_dir is None:
            raise HTTPException(status_code=404, detail=NO_PANEL_APPLY)
        return box, state, data_dir

    def view() -> TorUplinkView:
        box, _state, data = box_paths()
        tor = box.upstreams.tor
        return TorUplinkView(
            enabled=tor.enabled,
            bridges=[" ".join(line.split()[:2]) for line in tor.bridges],
            apply=_apply_view(data),
        )

    @application.get("/uplinks/tor", response_model=TorUplinkView)
    def tor_uplink() -> TorUplinkView:
        return view()

    @application.put("/uplinks/tor", response_model=TorUplinkView)
    def put_tor_uplink(request: TorUplinkUpdate) -> TorUplinkView:
        box, box_state, data = box_paths()
        if box.upstreams.tor.enabled == request.enabled:
            return view()
        _run_edit(box_state, lambda path: set_tor_uplink(path, request.enabled))
        _ask_host(data, "uplink tor " + ("enabled" if request.enabled else "disabled"))
        return view()


def _add_xray_uplink_routes(
    application: FastAPI,
    current: Callable[[], Config | None],
    state: BoxState | None,
    secrets_dir: Path | None,
    data_dir: Path | None,
) -> None:
    """``/uplinks/xray``: the masking exit turned on, off and pointed at a server from the panel
    (decision 29). The share link travels the same way a WireGuard file does — to core, into
    ``secrets/``, and never back out."""

    def box_paths() -> tuple[Config, BoxState, Path, Path]:
        box = current()
        if box is None or box.network is None or state is None or secrets_dir is None:
            raise HTTPException(status_code=404, detail=NO_PANEL_APPLY)
        if data_dir is None:
            raise HTTPException(status_code=404, detail=NO_PANEL_APPLY)
        return box, state, secrets_dir, data_dir

    def view() -> XrayUplinkView:
        box, _state, secrets, data = box_paths()
        link_path = secrets / XRAY_LINK_FILE
        seen = XrayUplinkView(
            enabled=box.upstreams.xray.enabled, linked=False, apply=_apply_view(data)
        )
        try:
            link = link_path.read_text(encoding="utf-8")
        except OSError:
            return seen
        try:
            server = parse_share_link(link)
        except XrayError as exc:
            return seen.model_copy(update={"linked": True, "problem": str(exc)})
        return seen.model_copy(
            update={
                "linked": True,
                "endpoint": server.endpoint,
                "transport": f"{server.network}/{server.security}",
                "remark": server.remark,
            }
        )

    @application.get("/uplinks/xray", response_model=XrayUplinkView)
    def xray_uplink() -> XrayUplinkView:
        return view()

    @application.put("/uplinks/xray", response_model=XrayUplinkView)
    def put_xray_uplink(request: XrayUplinkUpdate) -> XrayUplinkView:
        box, box_state, secrets, data = box_paths()
        if request.link is not None:
            try:
                parse_share_link(request.link)
            except XrayError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from None
            try:
                secrets.mkdir(mode=SECRET_DIR_MODE, exist_ok=True)
                write_private(secrets / XRAY_LINK_FILE, request.link.strip() + "\n")
            except OSError as exc:
                raise HTTPException(
                    status_code=500, detail=f"cannot write the link: {exc.strerror}"
                ) from exc
        # Turning it on without a link would start a gateway that leads nowhere.
        if request.enabled and not (secrets / XRAY_LINK_FILE).is_file():
            raise HTTPException(
                status_code=422,
                detail="uplink xray has no share link yet:"
                " give one here or run `vibedpn xray enable` on the box",
            )
        changed = box.upstreams.xray.enabled != request.enabled
        if changed:
            _run_edit(box_state, lambda path: set_xray_uplink(path, request.enabled))
        if changed or request.link is not None:
            _ask_host(data, "uplink xray " + ("enabled" if request.enabled else "disabled"))
        return view()


def _add_wg_uplink_routes(
    application: FastAPI,
    current: Callable[[], Config | None],
    state: BoxState | None,
    secrets_dir: Path | None,
    data_dir: Path | None,
) -> None:
    """``/uplinks/wg``: WireGuard exits added and removed in the panel (decision 26). core keeps
    the file and config.yaml; the host starts the exit when it applies the request core leaves."""

    def box_paths() -> tuple[Config, BoxState, Path, Path]:
        box = current()
        if box is None or box.network is None or state is None or secrets_dir is None:
            raise HTTPException(status_code=404, detail=NO_PANEL_APPLY)
        if data_dir is None:
            raise HTTPException(status_code=404, detail=NO_PANEL_APPLY)
        return box, state, secrets_dir, data_dir

    def checked_name(name: str) -> str:
        # the name reaches a path in secrets/: nothing but the documented form gets that far
        if not WG_UPLINK_NAME.fullmatch(name):
            raise HTTPException(
                status_code=422,
                detail=f"{name!r} is not a usable name: a-z, 0-9 and '-', up to 24 characters",
            )
        return name

    def view() -> WgUplinksView:
        box, _state, secrets, data = box_paths()
        return WgUplinksView(
            uplinks=[
                WgUplinkView(
                    name=name,
                    enabled=uplink.enabled,
                    has_file=(secrets / wg_uplink_file(name)).is_file(),
                )
                for name, uplink in sorted(box.upstreams.wg.items())
            ],
            apply=_apply_view(data),
        )

    ask_host = _ask_host

    @application.get("/uplinks/wg", response_model=WgUplinksView)
    def list_wg_uplinks() -> WgUplinksView:
        return view()

    @application.post("/uplinks/wg", response_model=WgUplinksView)
    def add_wg_uplink(request: WgUplinkCreate) -> WgUplinksView:
        _box, box_state, secrets, data = box_paths()
        name = checked_name(request.name)
        try:
            text = check_peer_text(request.config, "the file")
        except BootstrapError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        target = secrets / wg_uplink_file(name)
        existed = target.exists()
        write_private(target, text)
        try:
            _run_edit(box_state, lambda path: set_wg_uplink(path, name))
        except HTTPException:
            if not existed:  # a refused exit leaves no key behind
                target.unlink(missing_ok=True)
            raise
        ask_host(data, f"WireGuard exit {name} added")
        return view()

    @application.delete("/uplinks/wg/{name}", response_model=WgUplinksView)
    def remove_wg(name: str) -> WgUplinksView:
        _box, box_state, secrets, data = box_paths()
        checked = checked_name(name)
        _run_edit(box_state, lambda path: remove_wg_uplink(path, checked))
        # the private key of an exit the box no longer has does not stay on it
        (secrets / wg_uplink_file(checked)).unlink(missing_ok=True)
        ask_host(data, f"WireGuard exit {checked} removed")
        return view()


def _add_event_routes(
    application: FastAPI,
    current: Callable[[], Config | None],
    events: EventStore | None,
    device_store: DeviceStore | None,
    wifi_stations: WifiStations,
) -> None:
    """``/events``: the journal of the box; ``/wifi/clients``: who is on the access point now."""

    @application.get("/events", response_model=list[EventView])
    def list_events(
        kind: str | None = None, since: float | None = None, limit: int = DEFAULT_LIMIT
    ) -> list[EventView]:
        if events is None:
            raise HTTPException(status_code=404, detail=NO_JOURNAL)
        try:
            wanted = None if kind is None else EventKind(kind)
        except ValueError:
            known = ", ".join(item.value for item in EventKind)
            raise HTTPException(status_code=422, detail=f"kind is one of: {known}") from None
        try:
            found = events.events(
                kind=wanted, since=since, limit=min(max(limit, 1), MAX_EVENT_LIMIT)
            )
        except EventError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        names = device_names(current(), device_store)
        return [
            EventView(
                time=item.time,
                kind=item.kind.value,
                subject=item.subject,
                name=names.get(item.subject) if item.kind is EventKind.WIFI else None,
                action=item.action.value,
                detail=item.detail,
            )
            for item in found
        ]

    @application.get("/wifi/clients", response_model=list[WifiClientView])
    def wifi_clients() -> list[WifiClientView]:
        box = current()
        if box is None or box.network is None or box.network.wifi is None:
            raise HTTPException(status_code=404, detail=NO_ACCESS_POINT)
        try:
            stations = wifi_stations(box.network.lan_interface)
        except WifiError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        names = device_names(box, device_store)
        return [
            WifiClientView(
                mac=station.mac,
                name=names.get(station.mac),
                connected_seconds=station.connected_seconds,
                signal_dbm=station.signal_dbm,
                inactive_ms=station.inactive_ms,
                rx_bytes=station.rx_bytes,
                tx_bytes=station.tx_bytes,
            )
            for station in stations
        ]


def _add_device_routes(
    application: FastAPI,
    current: Callable[[], Config | None],
    state: BoxState | None,
    device_store: DeviceStore | None,
) -> None:
    """``/devices``: what discovery saw, and the policies of config.yaml changed at runtime."""

    def policy_edit(ident: str) -> tuple[BoxState, DeviceIdent]:
        box = current()
        if state is None or box is None or box.network is None:
            raise HTTPException(status_code=404, detail="this box routes no LAN")
        try:
            return state, DeviceIdent.parse(ident)
        except ConfigEditError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def discovered_name(target: DeviceIdent) -> str | None:
        if device_store is None:
            return None
        try:
            seen = device_store.devices()
        except DeviceError:
            return None
        found = next(
            (
                item
                for item in seen
                if (target.mac is not None and item.mac == target.mac)
                or (target.ip is not None and item.ip == target.ip)
            ),
            None,
        )
        return None if found is None else found.hostname

    def run_edit(box_state: BoxState, change: Callable[[Path], tuple[Config, bool]]) -> Config:
        try:
            return box_state.edit(change)
        except DeviceNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ConfigEditError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RouterError as exc:
            raise HTTPException(
                status_code=503, detail=f"router refused the change, config.yaml restored: {exc}"
            ) from exc

    @application.get("/devices", response_model=list[DeviceView])
    def devices() -> list[DeviceView]:
        box = current()
        if box is None or box.network is None or device_store is None:
            raise HTTPException(status_code=404, detail="this box routes no LAN")
        try:
            seen = device_store.devices()
        except DeviceError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return [_device_view(item, box.devices) for item in seen] + _unseen_views(seen, box.devices)

    @application.put("/devices/{ident}", response_model=DevicePolicyView)
    def put_device(ident: str, request: DevicePolicyUpdate) -> DevicePolicyView:
        box_state, target = policy_edit(ident)
        default_name = discovered_name(target) or target.default_name()
        updated = run_edit(
            box_state,
            lambda path: set_device(path, target, request.policy, request.name, default_name),
        )
        entry = next(
            item
            for item in updated.devices
            if (target.mac is not None and item.mac == target.mac)
            or (target.mac is None and item.ip == target.ip)
        )
        return DevicePolicyView(
            name=entry.name, mac=entry.mac, ip=entry.ip, policy=entry.policy.value
        )

    @application.delete("/devices/{ident}", status_code=204, response_class=Response)
    def delete_device(ident: str) -> Response:
        box_state, target = policy_edit(ident)
        run_edit(box_state, lambda path: unset_device(path, target))
        return Response(status_code=204)


def _uplink_statuses(
    box: Config, watchers: UplinkWatchers | None, facts: RoutingFacts
) -> list[UplinkStatus]:
    in_use = used_uplinks(box)
    states = {} if watchers is None else watchers.states()
    result = []
    for key in uplink_table(box):
        state = states.get(key)
        result.append(
            UplinkStatus(
                name=key,
                enabled=box.upstreams.is_key_enabled(key),
                in_use=key in in_use,
                gateway_alive=None if state is None else state.alive,
                checked_at=None
                if state is None
                else datetime.fromtimestamp(state.checked_at, tz=UTC),
                error="" if state is None else state.error,
                gateway_route=facts.gateway_routes.get(key),
                kill_switch_route=facts.last_resort_routes.get(key),
                lan_access=box.upstreams.vps.lan_access if key == Upstream.VPS.value else None,
            )
        )
    return result


def _dpn_statuses(consumer: ConsumerStatus | None) -> tuple[DpnStatus | None, list[DpnStatus]]:
    """The consumer of uplink dpn, and the ones of the rule countries in their order."""
    states = {} if consumer is None else consumer.states
    main = states.get(Upstream.DPN.value)
    countries = [
        _dpn_status(state) for key, state in states.items() if key.startswith(COUNTRY_KEY_PREFIX)
    ]
    return (None if main is None else _dpn_status(main)), countries


def _dpn_status(state: ConsumerState) -> DpnStatus:
    return DpnStatus(
        identity=state.identity,
        registration=state.registration,
        connection=state.connection,
        country=state.country,
        error=state.error,
        balance_wei=state.balance_wei,
        channel_address=state.channel_address,
    )


def _default_dpn_offers() -> list[CountryOffer]:
    client = TequilaClient(base_url=CONSUMER_TEQUILAPI, timeout=CONSUMER_TIMEOUT_SECONDS)
    try:
        return countries(client)
    finally:
        client.close()


def _default_consumer_client() -> TequilaClient:
    """The TequilAPI of the consumer gateway; asking about money is slow enough to need the long
    timeout of the consumer, not the short one of the provider."""
    return TequilaClient(base_url=CONSUMER_TEQUILAPI, timeout=CONSUMER_TIMEOUT_SECONDS)


def _add_dpn_routes(
    application: FastAPI,
    current: Callable[[], Config | None],
    state: BoxState | None,
    dpn_offers: DpnOffers,
) -> None:
    """``/dpn``: the countries the consumer can exit in, and the one config.yaml pins."""

    @application.get("/dpn/countries", response_model=list[DpnCountry])
    def dpn_countries() -> list[DpnCountry]:
        box = current()
        if box is None or box.network is None or not box.upstreams.dpn.enabled:
            raise HTTPException(status_code=404, detail="uplink dpn is off on this box")
        try:
            offers = dpn_offers()
        except MystError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return [
            DpnCountry(
                country=offer.country,
                nodes=offer.nodes,
                min_per_hour_wei=str(offer.min_per_hour_wei),
                min_per_gib_wei=str(offer.min_per_gib_wei),
            )
            for offer in offers
        ]

    @application.put("/dpn/country", response_model=DpnCountryView)
    def put_dpn_country(request: DpnCountryUpdate) -> DpnCountryView:
        box = current()
        if state is None or box is None or box.network is None:
            raise HTTPException(status_code=404, detail=NO_LAN)
        try:
            updated = state.edit(lambda path: set_dpn_country(path, request.country))
        except ConfigEditError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RouterError as exc:
            raise HTTPException(
                status_code=503, detail=f"router refused the change, config.yaml restored: {exc}"
            ) from exc
        return DpnCountryView(country=updated.upstreams.dpn.country)


def _add_dpn_registration_routes(
    application: FastAPI,
    current: Callable[[], Config | None],
    consumer_client: Callable[[], TequilaClient],
) -> None:
    """``/dpn/registration``: what it would cost, and the registration itself.

    The box never registers by itself (docs/decisions.md, 4): this is a transaction on the network
    and the money is the owner's. Asking the price spends nothing and creates no identity.
    """

    def identity_of(client: TequilaClient) -> str:
        box = current()
        if box is None or not box.upstreams.dpn.enabled:
            raise HTTPException(status_code=404, detail="uplink dpn is off on this box")
        try:
            identity = existing_identity(client)
        except MystError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if identity is None:
            raise HTTPException(status_code=503, detail="the node has no identity yet")
        return identity

    @application.get("/dpn/registration", response_model=DpnRegistrationView)
    def dpn_registration() -> DpnRegistrationView:
        client = consumer_client()
        identity = identity_of(client)
        try:
            offer = registration_offer(client, identity)
        except MystError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return DpnRegistrationView(
            identity=offer.identity,
            status=offer.status,
            free=offer.free,
            fee_wei=offer.fee_wei,
            balance_wei=offer.balance_wei,
            channel_address=offer.channel_address,
            affordable=offer.affordable,
        )

    @application.post("/dpn/registration", response_model=DpnRegistrationResult)
    def post_dpn_registration() -> DpnRegistrationResult:
        client = consumer_client()
        identity = identity_of(client)
        try:
            offer = registration_offer(client, identity)
            if offer.status == REGISTERED:
                return DpnRegistrationResult(result="registered", status=offer.status)
            if not offer.affordable:
                raise HTTPException(
                    status_code=422,
                    detail=f"not enough MYST for the fee: top up {offer.channel_address}",
                )
            return DpnRegistrationResult(result=register(client, identity), status=offer.status)
        except MystError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc


InterfacesSource = Callable[[], tuple[Interface | None, list[Interface]]]


def _host_interfaces() -> tuple[Interface | None, list[Interface]]:
    probe = HostProbe()
    return probe.default_interface(), probe.interfaces()


def _rule_view(rule: DomainRule) -> DomainRuleView:
    return DomainRuleView(
        domain=rule.domain,
        via=rule.via.value,
        country=rule.country,
        uplink=rule.uplink,
        learn=rule.learn,
        also=list(rule.also),
    )


def _add_lan_routes(
    application: FastAPI,
    state: BoxState | None,
    interfaces_source: InterfacesSource,
    smart: SmartLoop | None,
    lists: ListsStatus | None = None,
) -> None:
    """Network, domain rules and lists, and the DNS journal of a box with a LAN."""
    _add_network_routes(application, state, interfaces_source)
    _add_rule_routes(application, state)
    _add_list_routes(application, state, lists)
    _add_network_rule_routes(application, state)
    _add_smart_routes(application, smart)


def _add_smart_routes(application: FastAPI, smart: SmartLoop | None) -> None:
    """``/dns`` and ``/learned``: the sniffer and what routing.mode smart learned."""

    def loop() -> SmartLoop:
        if smart is None:
            raise HTTPException(status_code=404, detail="this box runs no AdGuard: no DNS journal")
        return smart

    @application.get("/dns/devices", response_model=list[JournalDeviceView])
    def dns_devices() -> list[JournalDeviceView]:
        journal = loop().journal
        return [
            JournalDeviceView(client=client, queries=len(journal.entries(client)))
            for client in journal.clients()
        ]

    @application.get("/dns/journal/{client}", response_model=list[JournalEntryView])
    def dns_journal(client: str, since: float = 0.0) -> list[JournalEntryView]:
        return [
            JournalEntryView(
                time=entry.time,
                name=entry.name,
                qtype=entry.qtype,
                cached=entry.cached,
                addresses=entry.addresses,
                channel=entry.channel,
                learned_from=entry.learned_from,
            )
            for entry in loop().journal.entries(client, since)
        ]

    @application.get("/learned", response_model=list[LearnedView])
    def learned() -> list[LearnedView]:
        try:
            names = loop().store.names()
        except LearnedError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return [
            LearnedView(
                name=item.name,
                parent=item.parent,
                source=item.source.value,
                first_seen=item.first_seen,
                last_seen=item.last_seen,
                hits=item.hits,
            )
            for item in names
        ]

    @application.delete("/learned/{name}", status_code=204)
    def forget_learned(name: str) -> Response:
        try:
            removed = loop().forget(name.lower().rstrip("."))
        except LearnedError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if not removed:
            raise HTTPException(status_code=404, detail=f"{name} was not learned")
        return Response(status_code=204)


def _lan_state(state: BoxState | None) -> BoxState:
    if state is None or state.config.routing is None:
        raise HTTPException(status_code=404, detail=NO_LAN)
    return state


def _run_edit(
    box_state: BoxState, change: Callable[[Path], tuple[Config, bool]], *, route: bool = True
) -> Config:
    """A rule or list edit of config.yaml applied live; core's refusals become HTTP answers."""
    try:
        return box_state.edit(change, route=route)
    except (
        RuleNotFoundError,
        ListNotFoundError,
        NetworkRuleNotFoundError,
        WgUplinkNotFoundError,
    ) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConfigEditError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RouterError as exc:
        raise HTTPException(
            status_code=503, detail=f"router refused the change, config.yaml restored: {exc}"
        ) from exc


def _list_view(item: DomainList, lists: ListsStatus | None) -> DomainListView:
    state = None if lists is None else lists.states.get(item.url)
    return DomainListView(
        url=item.url,
        via=item.via.value,
        country=item.country,
        uplink=item.uplink,
        domains=0 if state is None else state.domains,
        networks=0 if state is None else state.networks,
        fetched_at=None if state is None else state.fetched_at,
        error="" if state is None else state.error,
    )


def _add_list_routes(
    application: FastAPI, state: BoxState | None, lists: ListsStatus | None
) -> None:
    """``/lists``: ready domain lists of routing.lists, edited in config.yaml, fetched by core."""

    @application.get("/lists", response_model=list[DomainListView])
    def domain_lists() -> list[DomainListView]:
        routing = _lan_state(state).config.routing
        return [_list_view(item, lists) for item in routing.lists] if routing is not None else []

    @application.put("/lists", response_model=DomainListView)
    def put_list(request: DomainListUpdate) -> DomainListView:
        box_state = _lan_state(state)
        try:
            item = DomainList.model_validate(request.model_dump())
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()[0]["msg"]) from exc
        _run_edit(box_state, lambda path: set_domain_list(path, item))
        return _list_view(item, lists)

    @application.delete("/lists", status_code=204)
    def delete_list(url: str) -> Response:
        _run_edit(_lan_state(state), lambda path: remove_domain_list(path, url))
        return Response(status_code=204)


def _network_rule_view(rule: NetworkRule) -> NetworkRuleView:
    return NetworkRuleView(
        network=str(rule.network), via=rule.via.value, country=rule.country, uplink=rule.uplink
    )


def _add_network_rule_routes(application: FastAPI, state: BoxState | None) -> None:
    """``/networks``: address networks of smart mode, edited in config.yaml, applied live."""

    @application.get("/networks", response_model=list[NetworkRuleView])
    def network_rules() -> list[NetworkRuleView]:
        routing = _lan_state(state).config.routing
        return [_network_rule_view(rule) for rule in routing.networks] if routing else []

    @application.put("/networks", response_model=NetworkRuleView)
    def put_network_rule(request: NetworkRuleUpdate) -> NetworkRuleView:
        box_state = _lan_state(state)
        try:
            rule = NetworkRule.model_validate(request.model_dump())
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()[0]["msg"]) from exc
        _run_edit(box_state, lambda path: set_network_rule(path, rule))
        return _network_rule_view(rule)

    @application.delete("/networks", status_code=204)
    def delete_network_rule(network: str) -> Response:
        _run_edit(_lan_state(state), lambda path: remove_network_rule(path, network))
        return Response(status_code=204)


def _add_rule_routes(application: FastAPI, state: BoxState | None) -> None:
    """``/rules``: domain rules of routing.mode smart, edited in config.yaml, applied live."""

    @application.get("/rules", response_model=list[DomainRuleView])
    def rules() -> list[DomainRuleView]:
        routing = _lan_state(state).config.routing
        return [_rule_view(rule) for rule in routing.domains] if routing is not None else []

    @application.put("/rules/{domain}", response_model=DomainRuleView)
    def put_rule(domain: str, request: DomainRuleUpdate) -> DomainRuleView:
        box_state = _lan_state(state)
        try:
            rule = DomainRule.model_validate({"domain": domain, **request.model_dump()})
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()[0]["msg"]) from exc
        updated = _run_edit(box_state, lambda path: set_domain_rule(path, rule))
        routing = updated.routing
        saved = (
            next((item for item in routing.domains if item.domain == rule.domain), None)
            if routing
            else None
        )
        if saved is None:  # set_domain_rule wrote it; keeps the type narrow
            raise HTTPException(status_code=500, detail="the rule did not reach config.yaml")
        return _rule_view(saved)

    @application.delete("/rules/{domain}", status_code=204)
    def delete_rule(domain: str) -> Response:
        box_state = _lan_state(state)
        _run_edit(box_state, lambda path: remove_domain_rule(path, domain))
        return Response(status_code=204)


def _add_network_routes(
    application: FastAPI, state: BoxState | None, interfaces_source: InterfacesSource
) -> None:
    """``/network``: sidecar or gateway, saved for the next start of the box (decision 9)."""

    def detected() -> tuple[Interface | None, list[Interface]]:
        try:
            return interfaces_source()
        except DetectError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    def view(box_state: BoxState) -> NetworkView:
        network = box_state.saved.network
        if network is None:
            raise HTTPException(status_code=404, detail=NO_LAN)
        default, interfaces = detected()
        return NetworkView(
            mode=network.mode.value,
            lan_interface=network.lan_interface,
            lan_address=str(network.lan_address),
            wan_interface=network.wan_interface,
            restart_required=box_state.restart_required,
            interfaces=[
                HostInterface(
                    name=item.name,
                    address=str(item.address),
                    prefixlen=item.prefixlen,
                    default_route=default is not None and item.name == default.name,
                )
                for item in interfaces
            ],
        )

    def lan_state() -> BoxState:
        if state is None or state.config.network is None:
            raise HTTPException(status_code=404, detail=NO_LAN)
        return state

    @application.get("/network", response_model=NetworkView)
    def network() -> NetworkView:
        return view(lan_state())

    @application.put("/network", response_model=NetworkView)
    def put_network(request: NetworkUpdate) -> NetworkView:
        box_state = lan_state()
        default, interfaces = detected()
        if default is None:
            raise HTTPException(status_code=503, detail="the host has no default route")
        saved = box_state.saved.network
        same_lan = (
            saved is not None
            and saved.mode is NetworkMode.GATEWAY
            and request.lan_interface == saved.lan_interface
        )
        if saved is not None and saved.wifi is not None and not same_lan:
            raise HTTPException(
                status_code=422,
                detail=f"the Wi-Fi access point is on {saved.lan_interface}: remove network.wifi"
                " from config.yaml before moving the LAN",
            )
        kept = saved if same_lan else None
        try:
            wanted = network_for(
                request.lan_interface,
                interfaces,
                default,
                wifi=kept.wifi if kept is not None else None,
                dhcp=kept.dhcp if kept is not None else None,
            )
            box_state.save(lambda path: set_network(path, wanted))
        except (BootstrapError, ConfigEditError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return view(box_state)


def _dns_follower(dns_mode: DnsModeSetter, dns_reconnect: DnsReconnect) -> DnsFollower:
    """What AdGuard follows after a live change of the configuration"""

    def follow(before: Config, after: Config) -> AdguardFollows:
        """Its connections of an old path closed, its DNS mode told

        The upstreams go only when smart came or went: sending them restarts its DNS server
        """
        if dns_uplink(before) != dns_uplink(after):
            dns_reconnect(after)

        def smart(config: Config) -> bool:
            return config.routing is not None and config.routing.mode is RoutingMode.SMART

        try:
            return "none" if dns_mode(after, smart(before) != smart(after)) is None else "applied"
        except AdguardError:
            return "pending"

    return follow


def _add_config_routes(
    application: FastAPI,
    current: Callable[[], Config | None],
    state: BoxState | None,
    follow_dns: DnsFollower,
) -> None:
    """``/config/reread``: config.yaml edited by hand, applied by `vibedpn up` without a restart"""

    @application.post("/config/reread", response_model=ConfigRereadView)
    def reread_config() -> ConfigRereadView:
        box = current()
        if state is None or box is None:
            raise HTTPException(status_code=404, detail="this core keeps no live configuration")
        try:
            updated, changed = state.reread()
        except (ConfigError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=f"config.yaml: {exc}") from exc
        except RouterError as exc:
            raise HTTPException(
                status_code=503, detail=f"router refused config.yaml, core keeps its own: {exc}"
            ) from exc
        if not changed:
            return ConfigRereadView(changed=False)
        return ConfigRereadView(changed=True, adguard=follow_dns(box, updated))


def _add_routing_routes(
    application: FastAPI,
    current: Callable[[], Config | None],
    state: BoxState | None,
    watchers: UplinkWatchers | None,
    routing_reader: RoutingReader,
    follow_dns: DnsFollower,
    consumer: ConsumerStatus | None = None,
) -> None:
    """``/status`` and ``/routing``: the LAN router at a glance, and its mode changed live."""

    @application.get("/status", response_model=BoxStatus)
    def status() -> BoxStatus:
        box = current()
        if box is None or box.routing is None:
            raise HTTPException(status_code=404, detail=NO_LAN)
        routing = box.routing
        uplinks = _uplink_statuses(box, watchers, routing_reader(box))
        mode_uplink = next(item for item in uplinks if item.name == routing.default_upstream)
        dpn, dpn_countries = _dpn_statuses(consumer)
        return BoxStatus(
            mode=routing.mode.value,
            default_upstream=routing.default_upstream,
            failopen=routing.failopen,
            rules_current=routing_reader(box).rules_current,
            lan_without_exit=routing.mode is RoutingMode.FULL
            and mode_uplink.gateway_alive is False
            and not routing.failopen,
            uplinks=uplinks,
            dpn=dpn,
            dpn_countries=dpn_countries,
        )

    @application.put("/routing", response_model=RoutingView)
    def put_routing(request: RoutingUpdate) -> RoutingView:
        box = current()
        if state is None or box is None or box.routing is None:
            raise HTTPException(status_code=404, detail=NO_LAN)
        if request.mode is None and request.default_upstream is None:
            raise HTTPException(
                status_code=422, detail="nothing to change: give mode or default_upstream"
            )
        mode = None if request.mode is None else RoutingMode(request.mode)
        try:
            updated = state.edit(
                lambda path: set_routing(path, mode=mode, upstream=request.default_upstream)
            )
        except ConfigEditError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RouterError as exc:
            raise HTTPException(
                status_code=503, detail=f"router refused the change, config.yaml restored: {exc}"
            ) from exc
        adguard = follow_dns(box, updated)
        routing = updated.routing
        if routing is None:  # set_routing refuses a box without routing; keeps the type narrow
            raise HTTPException(status_code=404, detail=NO_LAN)
        return RoutingView(
            mode=routing.mode.value,
            default_upstream=routing.default_upstream,
            adguard=adguard,
        )

    @application.put("/uplinks/vps/lan-access", response_model=VpsLanAccessView)
    def put_vps_lan_access(request: VpsLanAccessUpdate) -> VpsLanAccessView:
        box = current()
        if state is None or box is None or box.network is None:
            raise HTTPException(status_code=404, detail=NO_LAN)
        try:
            updated = state.edit(lambda path: set_vps_lan_access(path, request.allowed))
        except ConfigEditError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RouterError as exc:
            raise HTTPException(
                status_code=503, detail=f"router refused the change, config.yaml restored: {exc}"
            ) from exc
        return VpsLanAccessView(allowed=updated.upstreams.vps.lan_access)


def create_app(
    config: Config | None = None,
    stats_source: StatsSource = _default_stats,
    secrets_dir: Path | None = None,
    link_source: LinkSource = read_wg_dump,
    device_store: DeviceStore | None = None,
    state: BoxState | None = None,
    watchers: UplinkWatchers | None = None,
    routing_reader: RoutingReader = read_routing,
    dns_mode: DnsModeSetter | None = None,
    dns_reconnect: DnsReconnect | None = None,
    consumer: ConsumerStatus | None = None,
    dpn_offers: DpnOffers | None = None,
    consumer_client: Callable[[], TequilaClient] | None = None,
    interfaces_source: InterfacesSource = _host_interfaces,
    smart: SmartLoop | None = None,
    lists: ListsStatus | None = None,
    events: EventStore | None = None,
    wifi_stations: WifiStations | None = None,
    data_dir: Path | None = None,
    access_dir: Path | None = None,
    access_owner: int | None = ACCESS_UID,
    telegram: TelegramBot | None = None,
) -> FastAPI:
    """Build the application. A factory keeps tests free of import-time side effects.

    ``config`` is the box configuration (``None`` before ``vibedpn-core`` loads it, e.g. in
    tests of ``/health``); ``secrets_dir`` is where the tunnel files live; ``stats_source`` and
    ``link_source`` are swapped in tests for a recorded node and a recorded interface.
    """
    application = FastAPI(title="VibeDPN core API", version=__version__)

    def current() -> Config | None:
        """The configuration as it is now: device policy edits change it at runtime."""
        return state.config if state is not None else config

    def tunnel() -> tuple[Config, Path]:
        box = current()
        if box is None or box.wg_server is None or secrets_dir is None:
            raise HTTPException(status_code=404, detail=NO_TUNNEL)
        return box, secrets_dir

    def default_dns_mode(box: Config, upstreams_changed: bool) -> bool | None:
        if secrets_dir is None:
            return None
        return set_dns_mode(box, secrets_dir, upstreams_changed=upstreams_changed)

    follow_dns = _dns_follower(dns_mode or default_dns_mode, dns_reconnect or reconnect_dns)
    _add_routing_routes(
        application,
        current,
        state,
        watchers,
        routing_reader,
        follow_dns,
        consumer,
    )
    _add_config_routes(application, current, state, follow_dns)
    _add_dpn_routes(application, current, state, dpn_offers or _default_dpn_offers)
    _add_dpn_registration_routes(application, current, consumer_client or _default_consumer_client)
    _add_lan_routes(application, state, interfaces_source, smart, lists)

    @application.get("/health", response_model=Health)
    def health() -> Health:
        return Health(status="ok", version=__version__)

    @application.get("/provider/stats", response_model=ProviderStats)
    def stats() -> ProviderStats:
        box = current()
        if box is None or not box.provider.enabled:
            raise HTTPException(status_code=404, detail="this box runs no provider node")
        try:
            return stats_source()
        except MystError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    _add_device_routes(application, current, state, device_store)
    _add_link_routes(
        application,
        current,
        state,
        LinkRouteSources(
            device_store, events, wifi_stations or read_stations, secrets_dir, data_dir
        ),
    )

    _add_peer_routes(application, tunnel, link_source, data_dir)
    _add_access_routes(
        application,
        current,
        state,
        AccessPaths(secrets_dir, data_dir, access_dir, access_owner),
    )
    _add_ddns_routes(application, current, state, secrets_dir, data_dir)
    _add_telegram_routes(application, current, state, telegram)
    _add_update_routes(application, data_dir)

    return application


def reconnect_dns(box: Config, exchange: Exchange = netlink_exchange) -> None:
    """Close the upstream connections of AdGuard after the uplink of its queries changed

    A failure leaves them as they were: the router is applied, and each fails one query at most
    """
    try:
        closed = close_upstream_connections(box, exchange)
    except SockDiagError as exc:
        sys.stderr.write(
            f"vibedpn-core: AdGuard keeps its upstream connections ({exc});"
            " the first name after the switch may fail once\n"
        )
        return
    if closed:
        sys.stderr.write(
            f"vibedpn-core: AdGuard upstream connections closed: {closed}, their path changed\n"
        )


def reconnect_on_failover(
    current: Callable[[], Config], reconnect: DnsReconnect = reconnect_dns
) -> Callable[[Event], None]:
    """A journal that closes the old connections of AdGuard when routing.failopen moves its queries

    With failopen, a silent gateway sends them direct and an answering one takes them back
    Either way the connections opened along the other path are dead
    Without failopen a silent gateway stops them all, and they come back along the same path
    """

    def follow(event: Event) -> None:
        if event.kind is not EventKind.UPLINK:
            return
        config = current()
        failopen = config.routing is not None and config.routing.failopen
        if failopen and event.subject == dns_uplink(config):
            reconnect(config)

    return follow


NO_ACCESS_FILES = "this core keeps no files for an access server"
QR_SCALE = 4
# A QR code needs light around it to be read, and the panel may be dark.
QR_LIGHT = "#ffffff"
QR_DARK = "#000000"


def _qr_svg(text: str) -> str:
    """The QR code as a whole SVG document. The panel shows it as an image, and an SVG loaded as an
    image draws nothing without its namespace — which ``svg_inline`` leaves out, for inline HTML."""
    buffer = io.BytesIO()
    segno.make(text, micro=False, error="m").save(
        buffer,
        kind="svg",
        xmldecl=False,
        svgns=True,
        nl=False,
        scale=QR_SCALE,
        dark=QR_DARK,
        light=QR_LIGHT,
    )
    return buffer.getvalue().decode("utf-8")


def _access_error(exc: AccessError) -> HTTPException:
    if isinstance(exc, PersonNameError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, PersonNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    # a name that is taken, or a server that is off: the request is fine, the state is not
    return HTTPException(status_code=409, detail=str(exc))


@dataclass(frozen=True)
class AccessPaths:
    secrets_dir: Path | None
    data_dir: Path | None
    access_dir: Path | None
    owner: int | None = ACCESS_UID  # who the server's files belong to; tests keep them their own


def _add_access_routes(
    application: FastAPI,
    current: Callable[[], Config | None],
    state: BoxState | None,
    paths: AccessPaths,
) -> None:
    """``/access``: the access server of the owner's people (decision 30) — on and off, the people
    and their links. Its key and the ids of the people stay in core; a link goes to whoever asked
    for it, and the panel shows it as a QR code."""

    def box_paths() -> tuple[Config, BoxState, Path, Path, Path]:
        box = current()
        secrets, data, directory = paths.secrets_dir, paths.data_dir, paths.access_dir
        if box is None or state is None or secrets is None or data is None or directory is None:
            raise HTTPException(status_code=404, detail=NO_ACCESS_FILES)
        return box, state, secrets, data, directory

    def view(since: str | None = None) -> AccessView:
        box, _state, secrets, data, _directory = box_paths()
        try:
            people = list_people(secrets)
        except AccessError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        with closing(traffic_connect(data / ACCESS_TRAFFIC_DIR)) as connection:
            used = {total.public_key: total for total in traffic_totals(connection, since)}
        return AccessView(
            enabled=box.access.enabled,
            address=box.access_address() or "",
            port=box.access.port,
            target=box.access.target,
            people=[
                AccessPerson(
                    name=person.name,
                    created=person.created,
                    rx_bytes=used[person.id].rx_bytes if person.id in used else 0,
                    tx_bytes=used[person.id].tx_bytes if person.id in used else 0,
                )
                for person in people
            ],
            apply=_apply_view(data),
        )

    @application.get("/access", response_model=AccessView)
    def access_server(since: str | None = None) -> AccessView:
        """The server and its people with what they used since a day (``YYYY-MM-DD``)."""
        return view(since)

    @application.put("/access", response_model=AccessView)
    def put_access_server(request: AccessUpdate) -> AccessView:
        box, box_state, secrets, data, directory = box_paths()
        edited = _run_edit(
            box_state,
            lambda path: set_access(
                path,
                enabled=request.enabled,
                address=request.address,
                port=request.port,
                target=request.target,
            ),
        )
        if edited.access.enabled:
            # ready before the host starts the container: it reads nothing else
            try:
                ensure_access(edited, secrets, directory, owner=paths.owner)
            except AccessError as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
        if edited.access != box.access:
            _ask_host(data, "access server " + ("enabled" if edited.access.enabled else "disabled"))
        return view()

    @application.post("/access/people", response_model=AccessLink, status_code=201)
    def create_person(request: AccessPersonCreate) -> AccessLink:
        box, _state, secrets, _data, directory = box_paths()
        try:
            person, link = add_person(box, secrets, directory, request.name, owner=paths.owner)
        except AccessError as exc:
            raise _access_error(exc) from exc
        return AccessLink(name=person.name, link=link, qr_svg=_qr_svg(link))

    @application.get("/access/people/{name}", response_model=AccessLink)
    def person(name: str) -> AccessLink:
        box, _state, secrets, _data, _directory = box_paths()
        try:
            link = person_link(box, secrets, name)
        except AccessError as exc:
            raise _access_error(exc) from exc
        return AccessLink(name=name, link=link, qr_svg=_qr_svg(link))

    @application.delete("/access/people/{name}", status_code=204, response_class=Response)
    def delete_person(name: str) -> Response:
        box, _state, secrets, data, directory = box_paths()
        try:
            removed = remove_person(box, secrets, directory, name, owner=paths.owner)
        except AccessError as exc:
            raise _access_error(exc) from exc
        # their totals go with them: a person added under the same name later starts from zero
        with closing(traffic_connect(data / ACCESS_TRAFFIC_DIR)) as connection:
            traffic_forget(connection, removed.id)
        return Response(status_code=204)


def _add_ddns_routes(
    application: FastAPI,
    current: Callable[[], Config | None],
    state: BoxState | None,
    secrets_dir: Path | None,
    data_dir: Path | None,
) -> None:
    """``/ddns``: the name that follows the public address of the box. The update URL goes in and
    never comes back out: it carries a token."""

    def box_paths() -> tuple[Config, BoxState, Path, Path]:
        box = current()
        if box is None or state is None or secrets_dir is None or data_dir is None:
            raise HTTPException(status_code=404, detail=NO_ACCESS_FILES)
        return box, state, secrets_dir, data_dir

    def view() -> DdnsView:
        box, _state, secrets, data = box_paths()
        url = load_ddns_url(secrets)
        known = load_ddns_state(data / DDNS_STATE_FILE)
        return DdnsView(
            enabled=box.ddns.enabled,
            url_set=url is not None,
            host="" if url is None else ddns_host(url),
            public_ip=known.public_ip,
            told_ip=known.told_ip,
            last_ok=known.last_ok,
            last_at=known.last_at,
            message=known.message,
            address_error=known.address_error,
            apply=_apply_view(data),
        )

    @application.get("/ddns", response_model=DdnsView)
    def ddns() -> DdnsView:
        return view()

    @application.put("/ddns", response_model=DdnsView)
    def put_ddns(request: DdnsUpdate) -> DdnsView:
        box, box_state, secrets, data = box_paths()
        if request.url is not None:
            try:
                secrets.mkdir(mode=SECRET_DIR_MODE, exist_ok=True)
                save_ddns_url(secrets, request.url)
            except DdnsError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except OSError as exc:
                raise HTTPException(
                    status_code=500, detail=f"cannot keep the update URL: {exc.strerror}"
                ) from exc
        if request.enabled and load_ddns_url(secrets) is None:
            raise HTTPException(status_code=422, detail="ddns has no update URL yet: give one here")
        edited = _run_edit(box_state, lambda path: set_ddns(path, request.enabled))
        if edited.ddns != box.ddns:
            _ask_host(data, "ddns " + ("enabled" if request.enabled else "disabled"))
        return view()


NO_TELEGRAM = "this core runs no Telegram bot"


def _telegram_error(exc: TelegramError) -> HTTPException:
    if exc.rejected:
        return HTTPException(
            status_code=422, detail=f"Telegram does not know this token ({exc}): check it"
        )
    return HTTPException(status_code=503, detail=str(exc))


def _add_telegram_routes(
    application: FastAPI,
    current: Callable[[], Config | None],
    state: BoxState | None,
    bot: TelegramBot | None,
) -> None:
    """``/telegram``: the bot of the box (decision 31) — its settings in config.yaml, applied
    live; its token, which goes into ``secrets/`` and never back out; the link that links a chat,
    with its QR code; a test message."""

    def box_bot() -> tuple[Config, BoxState, TelegramBot]:
        box = current()
        if box is None or state is None or bot is None:
            raise HTTPException(status_code=404, detail=NO_TELEGRAM)
        return box, state, bot

    def view() -> TelegramView:
        box, _state, telegram = box_bot()
        status = telegram.status()
        offer = status.offer
        link = link_url(status.bot, offer.code) if offer is not None and status.bot else None
        settings = box.telegram
        return TelegramView(
            enabled=settings.enabled,
            token_set=status.token_set,
            bot=status.bot,
            linked=status.linked,
            chat=status.chat,
            linked_at=status.linked_at,
            link=link,
            qr_svg=_qr_svg(link) if link is not None else None,
            link_expires_at=offer.expires_at if link is not None and offer is not None else None,
            alert_after_seconds=settings.alert_after_seconds,
            timezone=settings.timezone,
            report=TelegramReportView(
                enabled=settings.report.enabled,
                weekday=settings.report.weekday,
                hour=settings.report.hour,
            ),
            last_ok=status.delivery.last_ok,
            last_at=status.delivery.last_at,
            message=status.delivery.message,
            via=status.delivery.via,
            waiting=status.waiting,
        )

    def enable(box_state: BoxState) -> None:
        _run_edit(box_state, lambda path: set_telegram(path, enabled=True), route=False)

    @application.get("/telegram", response_model=TelegramView)
    def telegram_bot() -> TelegramView:
        return view()

    @application.put("/telegram", response_model=TelegramView)
    def put_telegram_bot(request: TelegramUpdate) -> TelegramView:
        _box, box_state, telegram = box_bot()
        if request.enabled and not telegram.status().token_set:
            raise HTTPException(
                status_code=422, detail="the bot has no token yet: vibedpn telegram set"
            )
        _run_edit(
            box_state,
            lambda path: set_telegram(
                path,
                enabled=request.enabled,
                alert_after_seconds=request.alert_after_seconds,
                timezone=request.timezone,
                report_enabled=request.report_enabled,
                report_weekday=request.report_weekday,
                report_hour=request.report_hour,
            ),
            route=False,
        )
        return view()

    @application.post("/telegram/token", response_model=TelegramView)
    def put_telegram_token(request: TelegramToken) -> TelegramView:
        """Check the token with Telegram, keep it, turn the bot on and offer a link."""
        _box, box_state, telegram = box_bot()
        try:
            token = check_token(request.token)
        except TelegramError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            telegram.set_token(token)
        except TelegramError as exc:
            raise _telegram_error(exc) from exc
        except OSError as exc:
            raise HTTPException(
                status_code=500, detail=f"cannot keep the token: {exc.strerror or exc}"
            ) from exc
        enable(box_state)
        return view()

    @application.post("/telegram/link", response_model=TelegramView)
    def telegram_link() -> TelegramView:
        _box, _state, telegram = box_bot()
        try:
            telegram.offer_link()
        except TelegramError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return view()

    @application.post("/telegram/test", status_code=204, response_class=Response)
    def telegram_test() -> Response:
        _box, _state, telegram = box_bot()
        if not telegram.status().linked:
            raise HTTPException(
                status_code=409, detail="no chat is linked yet: vibedpn telegram link"
            )
        try:
            telegram.test()
        except TelegramError as exc:
            raise _telegram_error(exc) from exc
        return Response(status_code=204)


def _add_peer_routes(
    application: FastAPI,
    tunnel: Callable[[], tuple[Config, Path]],
    link_source: Callable[[], dict[str, PeerLink] | None],
    data_dir: Path | None,
) -> None:
    """The peers of a VPS: who is registered, how much they used, and adding or removing one."""

    @application.get("/peers", response_model=list[PeerView])
    def peers() -> list[PeerView]:
        box, secrets = tunnel()
        try:
            registered = list_peers(box, secrets)
        except WgError as exc:
            raise _http_error(exc) from exc
        links = link_source() if registered else None
        return [_view(peer, links) for peer in registered]

    @application.get("/peers/traffic", response_model=list[PeerTraffic])
    def peers_traffic(since: str | None = None) -> list[PeerTraffic]:
        """Totals per peer since a day (``YYYY-MM-DD``), or since the box started counting."""
        box, secrets = tunnel()
        try:
            names = {peer.public_key: peer.name for peer in list_peers(box, secrets)}
        except WgError as exc:
            raise _http_error(exc) from exc
        if data_dir is None:  # a box that keeps nothing on disk counts nothing either
            return []
        with closing(traffic_connect(data_dir)) as connection:
            return [
                PeerTraffic(
                    name=names.get(total.public_key, ""),
                    public_key=total.public_key,
                    rx_bytes=total.rx_bytes,
                    tx_bytes=total.tx_bytes,
                )
                for total in traffic_totals(connection, since)
            ]

    @application.post("/peers", response_model=PeerFile, status_code=201)
    def create_peer(request: PeerCreate) -> PeerFile:
        box, secrets = tunnel()
        try:
            peer = add_peer(box, secrets, request.name, tunnel_only=request.tunnel_only)
            text = peer_config(box, secrets, peer.name)
        except WgError as exc:
            raise _http_error(exc) from exc
        return PeerFile(name=peer.name, address=peer.address, config=text)

    @application.get("/peers/{name}/config", response_model=PeerFile)
    def export_peer(name: str) -> PeerFile:
        box, secrets = tunnel()
        try:
            peer = find_peer(box, secrets, name)
            text = peer_config(box, secrets, name)
        except WgError as exc:
            raise _http_error(exc) from exc
        return PeerFile(name=peer.name, address=peer.address, config=text)

    @application.delete("/peers/{name}", status_code=204, response_class=Response)
    def delete_peer(name: str) -> Response:
        box, secrets = tunnel()
        try:
            peer = find_peer(box, secrets, name)
            remove_peer(box, secrets, name)
        except WgError as exc:
            raise _http_error(exc) from exc
        # Its totals go with it: they are of no use to anyone, and a peer added under the same name
        # later would inherit them.
        if data_dir is not None:
            with closing(traffic_connect(data_dir)) as connection:
                traffic_forget(connection, peer.public_key)
        return Response(status_code=204)
