"""ASGI application factory: health, provider statistics (Stage 2) and tunnel peers (Stage 3)."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

from vibedpn import __version__
from vibedpn.api.consumer import ConsumerStatus
from vibedpn.api.models import (
    BoxStatus,
    DevicePolicyUpdate,
    DevicePolicyView,
    DeviceView,
    DpnStatus,
    PeerCreate,
    PeerFile,
    PeerView,
    RoutingUpdate,
    RoutingView,
    UplinkStatus,
    VpsLanAccessUpdate,
    VpsLanAccessView,
)
from vibedpn.api.state import BoxState
from vibedpn.api.uplink import UplinkWatchers
from vibedpn.config import Config, DeviceConfig, RoutingMode, Upstream
from vibedpn.config_edit import (
    ConfigEditError,
    DeviceIdent,
    DeviceNotFoundError,
    set_device,
    set_routing,
    set_vps_lan_access,
    unset_device,
)
from vibedpn.engine.adguard import AdguardError, set_aaaa_disabled
from vibedpn.engine.devices import DeviceError, DeviceStore, SeenDevice
from vibedpn.engine.myst import MystError, ProviderStats, TequilaClient, provider_stats
from vibedpn.engine.router import RouterError, RoutingFacts, read_routing, used_uplinks
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

StatsSource = Callable[[], ProviderStats]
RoutingReader = Callable[[Config], RoutingFacts]
# Tells the running AdGuard the DNS mode; None: no AdGuard on this box.
DnsModeSetter = Callable[[Config], bool | None]
NO_LAN = "this box routes no LAN"
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
    for upstream in (Upstream.VPS, Upstream.DPN):
        state = states.get(upstream)
        result.append(
            UplinkStatus(
                name=upstream.value,
                enabled=box.upstreams.is_enabled(upstream),
                in_use=upstream in in_use,
                gateway_alive=None if state is None else state.alive,
                checked_at=None
                if state is None
                else datetime.fromtimestamp(state.checked_at, tz=UTC),
                error="" if state is None else state.error,
                gateway_route=facts.gateway_routes.get(upstream.value),
                kill_switch_route=facts.last_resort_routes.get(upstream.value),
                lan_access=box.upstreams.vps.lan_access if upstream is Upstream.VPS else None,
            )
        )
    return result


def _dpn_status(consumer: ConsumerStatus | None) -> DpnStatus | None:
    state = None if consumer is None else consumer.state
    if state is None:
        return None
    return DpnStatus(
        identity=state.identity,
        registration=state.registration,
        connection=state.connection,
        country=state.country,
        error=state.error,
    )


def _add_routing_routes(
    application: FastAPI,
    current: Callable[[], Config | None],
    state: BoxState | None,
    watchers: UplinkWatchers | None,
    routing_reader: RoutingReader,
    dns_mode: DnsModeSetter,
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
        mode_uplink = next(item for item in uplinks if item.name == routing.default_upstream.value)
        return BoxStatus(
            mode=routing.mode.value,
            default_upstream=routing.default_upstream.value,
            failopen=routing.failopen,
            rules_current=routing_reader(box).rules_current,
            lan_without_exit=routing.mode is RoutingMode.FULL
            and mode_uplink.gateway_alive is False
            and not routing.failopen,
            uplinks=uplinks,
            dpn=_dpn_status(consumer),
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
        adguard: Literal["applied", "pending", "none"]
        try:
            adguard = "none" if dns_mode(updated) is None else "applied"
        except AdguardError:
            adguard = "pending"
        routing = updated.routing
        if routing is None:  # set_routing refuses a box without routing; keeps the type narrow
            raise HTTPException(status_code=404, detail=NO_LAN)
        return RoutingView(
            mode=routing.mode.value,
            default_upstream=routing.default_upstream.value,
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
    consumer: ConsumerStatus | None = None,
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

    def default_dns_mode(box: Config) -> bool | None:
        if secrets_dir is None:
            return None
        return set_aaaa_disabled(box, secrets_dir)

    _add_routing_routes(
        application,
        current,
        state,
        watchers,
        routing_reader,
        dns_mode or default_dns_mode,
        consumer,
    )

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

    @application.get("/peers", response_model=list[PeerView])
    def peers() -> list[PeerView]:
        box, secrets = tunnel()
        try:
            registered = list_peers(box, secrets)
        except WgError as exc:
            raise _http_error(exc) from exc
        links = link_source() if registered else None
        return [_view(peer, links) for peer in registered]

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
            remove_peer(box, secrets, name)
        except WgError as exc:
            raise _http_error(exc) from exc
        return Response(status_code=204)

    return application
