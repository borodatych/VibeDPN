"""ASGI application factory: health, provider statistics (Stage 2) and tunnel peers (Stage 3)."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, ValidationError

from vibedpn import __version__
from vibedpn.api.consumer import ConsumerStatus
from vibedpn.api.models import (
    BoxStatus,
    DevicePolicyUpdate,
    DevicePolicyView,
    DeviceView,
    DomainRuleUpdate,
    DomainRuleView,
    DpnCountry,
    DpnCountryUpdate,
    DpnCountryView,
    DpnStatus,
    HostInterface,
    JournalDeviceView,
    JournalEntryView,
    LearnedView,
    NetworkUpdate,
    NetworkView,
    PeerCreate,
    PeerFile,
    PeerView,
    RoutingUpdate,
    RoutingView,
    UplinkStatus,
    VpsLanAccessUpdate,
    VpsLanAccessView,
)
from vibedpn.api.smart import SmartLoop
from vibedpn.api.state import BoxState
from vibedpn.api.uplink import UplinkWatchers
from vibedpn.bootstrap import BootstrapError, network_for
from vibedpn.config import Config, DeviceConfig, DomainRule, NetworkMode, RoutingMode, Upstream
from vibedpn.config_edit import (
    ConfigEditError,
    DeviceIdent,
    DeviceNotFoundError,
    RuleNotFoundError,
    remove_domain_rule,
    set_device,
    set_domain_rule,
    set_dpn_country,
    set_network,
    set_routing,
    set_vps_lan_access,
    unset_device,
)
from vibedpn.detect import DetectError, HostProbe, Interface
from vibedpn.engine.adguard import AdguardError, set_dns_mode
from vibedpn.engine.consumer import (
    CONSUMER_TEQUILAPI,
    CONSUMER_TIMEOUT_SECONDS,
    ConsumerState,
    CountryOffer,
    countries,
)
from vibedpn.engine.devices import DeviceError, DeviceStore, SeenDevice
from vibedpn.engine.learned import LearnedError
from vibedpn.engine.myst import MystError, ProviderStats, TequilaClient, provider_stats
from vibedpn.engine.router import (
    COUNTRY_KEY_PREFIX,
    RouterError,
    RoutingFacts,
    read_routing,
    uplink_table,
    used_uplinks,
)
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
DnsModeSetter = Callable[[Config, bool], bool | None]  # the box, did smart come or go
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
        upstream = Upstream.DPN if key.startswith(COUNTRY_KEY_PREFIX) else Upstream(key)
        state = states.get(key)
        result.append(
            UplinkStatus(
                name=key,
                enabled=box.upstreams.is_enabled(upstream),
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


InterfacesSource = Callable[[], tuple[Interface | None, list[Interface]]]


def _host_interfaces() -> tuple[Interface | None, list[Interface]]:
    probe = HostProbe()
    return probe.default_interface(), probe.interfaces()


def _rule_view(rule: DomainRule) -> DomainRuleView:
    return DomainRuleView(
        domain=rule.domain,
        via=rule.via.value,
        country=rule.country,
        learn=rule.learn,
        also=list(rule.also),
    )


def _add_lan_routes(
    application: FastAPI,
    state: BoxState | None,
    interfaces_source: InterfacesSource,
    smart: SmartLoop | None,
) -> None:
    """Network, domain rules and the DNS journal of a box with a LAN."""
    _add_network_routes(application, state, interfaces_source)
    _add_rule_routes(application, state)
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


def _add_rule_routes(application: FastAPI, state: BoxState | None) -> None:
    """``/rules``: domain rules of routing.mode smart, edited in config.yaml, applied live."""

    def lan_state() -> BoxState:
        if state is None or state.config.routing is None:
            raise HTTPException(status_code=404, detail=NO_LAN)
        return state

    def run_edit(box_state: BoxState, change: Callable[[Path], tuple[Config, bool]]) -> Config:
        try:
            return box_state.edit(change)
        except RuleNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ConfigEditError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RouterError as exc:
            raise HTTPException(
                status_code=503, detail=f"router refused the change, config.yaml restored: {exc}"
            ) from exc

    @application.get("/rules", response_model=list[DomainRuleView])
    def rules() -> list[DomainRuleView]:
        routing = lan_state().config.routing
        return [_rule_view(rule) for rule in routing.domains] if routing is not None else []

    @application.put("/rules/{domain}", response_model=DomainRuleView)
    def put_rule(domain: str, request: DomainRuleUpdate) -> DomainRuleView:
        box_state = lan_state()
        try:
            rule = DomainRule.model_validate({"domain": domain, **request.model_dump()})
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()[0]["msg"]) from exc
        updated = run_edit(box_state, lambda path: set_domain_rule(path, rule))
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
        box_state = lan_state()
        run_edit(box_state, lambda path: remove_domain_rule(path, domain))
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
        dpn, dpn_countries = _dpn_statuses(consumer)
        return BoxStatus(
            mode=routing.mode.value,
            default_upstream=routing.default_upstream.value,
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
        adguard: Literal["applied", "pending", "none"]
        try:
            entered_or_left_smart = (box.routing.mode is RoutingMode.SMART) != (
                updated.routing is not None and updated.routing.mode is RoutingMode.SMART
            )
            adguard = "none" if dns_mode(updated, entered_or_left_smart) is None else "applied"
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
    dpn_offers: DpnOffers | None = None,
    interfaces_source: InterfacesSource = _host_interfaces,
    smart: SmartLoop | None = None,
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

    _add_routing_routes(
        application,
        current,
        state,
        watchers,
        routing_reader,
        dns_mode or default_dns_mode,
        consumer,
    )
    _add_dpn_routes(application, current, state, dpn_offers or _default_dpn_offers)
    _add_lan_routes(application, state, interfaces_source, smart)

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
