"""Console entry point of the ``core`` container: load ``config.yaml`` and serve the API.

The full API binds loopback only. The ``ui`` panel exposes it on the LAN interface under
``/api/core/`` to a signed-in session; on a VPS home boxes reach a read-only part of it, and the
node panel, on the tunnel address (``vibedpn.api.tunnel``).
"""

import os
import sys
from collections import deque
from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path

import httpx
from pydantic import ValidationError

from vibedpn.api.app import create_app
from vibedpn.api.background import BackgroundLoop
from vibedpn.api.consumer import ConsumerStatus, consumer_round, watch_consumer
from vibedpn.api.journal import Journal, fan_out, ignore_event, store_journal
from vibedpn.api.lists import ListsStatus, watch_lists
from vibedpn.api.smart import DnsJournal, SmartLoop, watch_querylog
from vibedpn.api.state import BoxState
from vibedpn.api.telegram import TelegramBot
from vibedpn.api.traffic import ACCESS_TRAFFIC_DIR, access_samples, watch_traffic
from vibedpn.api.tunnel import run_servers
from vibedpn.api.uplink import UplinkWatchers
from vibedpn.api.wifi import watch_wifi
from vibedpn.config import Config, ConfigError, load_config
from vibedpn.engine import hostapd
from vibedpn.engine.access import AccessError, ensure_access
from vibedpn.engine.adguard import (
    AdguardError,
    ensure_adguard,
    give_to_adguard,
    querylog_fetcher,
)
from vibedpn.engine.ddns import STATE_FILE as DDNS_STATE_FILE
from vibedpn.engine.ddns import watch_ddns
from vibedpn.engine.devices import DB_FILE, DeviceError, DeviceStore
from vibedpn.engine.dnsmasq import DnsmasqError, core_dir, ensure_dnsmasq
from vibedpn.engine.domainlists import LISTS_DIR, ListCache, http_fetch, list_client
from vibedpn.engine.events import DB_FILE as EVENTS_FILE
from vibedpn.engine.events import Event, EventError, EventStore
from vibedpn.engine.i18n import LOCALES_DIR, load_catalog
from vibedpn.engine.learned import LEARNED_FILE, LearnedError, LearnedStore
from vibedpn.engine.resolver import (
    UPSTREAM_TIMEOUT_SECONDS,
    Resolver,
    RuleIndex,
    doh_exchange,
    serve_resolver,
)
from vibedpn.engine.router import (
    ADGUARD_UID,
    EGRESS_TABLE,
    ROUTER_TABLE,
    Egress,
    RouterError,
    apply_firewall,
    apply_router,
    apply_tunnel_egress,
    uplink_table,
)
from vibedpn.engine.telegram import TelegramError, resolver_lookup, system_lookup
from vibedpn.engine.wg import WgError, ensure_server

EGRESS_MESSAGES = {
    Egress.NONE: f"no tunnel in this configuration; table {EGRESS_TABLE} removed if it was loaded",
    Egress.DOCKER_USER: (
        f"tunnel egress applied (table {EGRESS_TABLE}, forward opened in DOCKER-USER)"
    ),
    Egress.NO_DOCKER_DROP: (
        f"tunnel egress applied (table {EGRESS_TABLE}; no DOCKER-USER chain, nothing to open)"
    ),
}


def router_message(config: Config, uplinks: Sequence[str]) -> str:
    if config.network is None:
        return f"no LAN in this configuration; table {ROUTER_TABLE} removed if it was loaded"
    mode = config.routing.mode.value if config.routing is not None else "off"
    if not uplinks:
        return f"LAN router applied (table {ROUTER_TABLE}): routing.mode {mode}, LAN goes direct"
    names = ", ".join(uplinks)
    return (
        f"LAN router applied (table {ROUTER_TABLE}): routing.mode {mode}, uplinks in use: {names};"
        " their traffic waits for the gateways to answer"
    )


CONFIG_PATH_ENV = "VIBEDPN_CONFIG"
# compose.yaml mounts the box directory: core rewrites config.yaml atomically, which a rename over
# a single bind-mounted file does not allow (EBUSY).
DEFAULT_CONFIG_PATH = Path("/etc/vibedpn/box/config.yaml")
SECRETS_DIR_ENV = "VIBEDPN_SECRETS"
DEFAULT_SECRETS_DIR = Path("/etc/vibedpn/secrets")  # compose.yaml mounts ./secrets here
ADGUARD_DIR_ENV = "VIBEDPN_ADGUARD_CONF"
DEFAULT_ADGUARD_DIR = Path("/etc/vibedpn/adguard")  # compose.yaml mounts ./data/adguard/conf
ADGUARD_WORK_DIR_ENV = "VIBEDPN_ADGUARD_WORK"
DEFAULT_ADGUARD_WORK_DIR = Path("/etc/vibedpn/adguard-work")  # ./data/adguard/work
DATA_DIR_ENV = "VIBEDPN_DATA"
DEFAULT_DATA_DIR = Path("/var/lib/vibedpn")  # compose.yaml mounts ./data/core
ACCESS_DIR_ENV = "VIBEDPN_ACCESS_DIR"
DEFAULT_ACCESS_DIR = Path("/etc/vibedpn/access")  # compose.yaml mounts ./data/access


def main() -> None:
    """Serve the API on the port from ``api.port`` of the box config.

    A missing or invalid config is a user error: one readable message, exit code ``EX_CONFIG``.
    """
    config_path = Path(os.environ.get(CONFIG_PATH_ENV, DEFAULT_CONFIG_PATH))
    try:
        config = load_config(config_path)
    except (ConfigError, ValidationError) as exc:
        sys.stderr.write(f"vibedpn-core: cannot start: {exc}\n")
        raise SystemExit(os.EX_CONFIG) from None
    try:
        if apply_firewall(config):
            sys.stderr.write("vibedpn-core: host firewall applied (table inet vibedpn)\n")
        else:
            sys.stderr.write(
                "vibedpn-core: no host firewall in this configuration;"
                " table inet vibedpn removed if it was loaded\n"
            )
        egress = apply_tunnel_egress(config)
        sys.stderr.write(f"vibedpn-core: {EGRESS_MESSAGES[egress]}\n")
        uplinks = apply_router(config)
        sys.stderr.write(f"vibedpn-core: {router_message(config, uplinks)}\n")
    except RouterError as exc:
        sys.stderr.write(f"vibedpn-core: cannot start: {exc}\n")
        raise SystemExit(os.EX_CONFIG) from None
    secrets_dir = Path(os.environ.get(SECRETS_DIR_ENV, DEFAULT_SECRETS_DIR))
    # Before the API, like the tunnel below: compose starts adguard only once core is healthy.
    adguard_dir = Path(os.environ.get(ADGUARD_DIR_ENV, DEFAULT_ADGUARD_DIR))
    data_dir = Path(os.environ.get(DATA_DIR_ENV, DEFAULT_DATA_DIR))
    try:
        adguard = ensure_adguard(config, adguard_dir, secrets_dir, data_dir)
    except AdguardError as exc:
        sys.stderr.write(f"vibedpn-core: cannot start: {exc}\n")
        raise SystemExit(os.EX_CONFIG) from None
    _report("AdGuard Home", adguard)
    _hand_adguard_dirs(config, adguard_dir)
    _render_lan_services(config, secrets_dir)
    # Before the API: compose starts wg-server only once core is healthy, so the file it reads
    # is always the one rendered from the current config.
    try:
        files = ensure_server(config, secrets_dir)
    except WgError as exc:
        sys.stderr.write(f"vibedpn-core: cannot start: {exc}\n")
        raise SystemExit(os.EX_CONFIG) from None
    if files is not None:
        sys.stderr.write(f"vibedpn-core: WireGuard server config rendered ({files.conf.name})\n")
        for moved in files.renumbered:
            # The owner changed wg_server.subnet: this box needs its peer file exported again.
            sys.stderr.write(
                f"vibedpn-core: peer {moved.name} moved from {moved.old} to {moved.new};"
                f" run `vibedpn peer export {moved.name}` for its home box\n"
            )
    access_dir = Path(os.environ.get(ACCESS_DIR_ENV, DEFAULT_ACCESS_DIR))
    _render_access(config, secrets_dir, access_dir)
    devices, events, stored = _lan_stores(config, data_dir)
    # the Telegram bot hears every event the store keeps; it drains them on its own loop
    inbox: deque[Event] = deque()
    journal = fan_out(stored, inbox.append)
    watchers = _watchers(config, uplinks, journal)
    box_state, resolver, smart, lists = _box_state(
        config, config_path, watchers, secrets_dir, data_dir
    )
    bot = _telegram_bot(
        config, config_path, box_state, resolver, watchers, inbox, secrets_dir, data_dir
    )
    consumer = ConsumerStatus()
    application = create_app(
        config,
        secrets_dir=secrets_dir,
        device_store=devices,
        state=box_state,
        watchers=watchers,
        consumer=consumer,
        smart=smart,
        lists=lists,
        events=events,
        data_dir=data_dir,
        access_dir=access_dir,
        telegram=bot,
    )
    run_servers(
        config,
        application,
        watchers=watchers,
        devices=devices,
        extra=[
            *_consumer_task(config, box_state, consumer, secrets_dir),
            *_traffic_task(config, data_dir),
            *_access_traffic_task(config, secrets_dir, data_dir),
            *_ddns_task(config, box_state, secrets_dir, data_dir),
            BackgroundLoop("telegram bot", bot.run),
            *(
                [BackgroundLoop("resolver", partial(serve_resolver, resolver))]
                if resolver is not None
                else []
            ),
            *(
                [BackgroundLoop("smart query log", partial(watch_querylog, smart))]
                if smart is not None
                else []
            ),
            *_list_task(box_state, resolver, lists, data_dir),
            # returns at once on a box without network.wifi
            *(
                [BackgroundLoop("Wi-Fi journal", partial(watch_wifi, config, journal))]
                if events is not None
                else []
            ),
        ],
    )


def _traffic_task(config: Config, data_dir: Path) -> list[BackgroundLoop]:
    """Counting what the peers of a VPS use; a box without a tunnel server counts nobody."""
    if config.wg_server is None:
        return []
    return [BackgroundLoop("peer traffic counter", partial(watch_traffic, data_dir))]


def _render_access(config: Config, secrets_dir: Path, access_dir: Path) -> None:
    """Before the API, like the tunnel: compose starts the access server only once core is healthy,
    so the files it reads are always the ones rendered from the current config."""
    try:
        files = ensure_access(config, secrets_dir, access_dir)
    except AccessError as exc:
        sys.stderr.write(f"vibedpn-core: cannot start: {exc}\n")
        raise SystemExit(os.EX_CONFIG) from None
    if files is not None:
        sys.stderr.write(
            f"vibedpn-core: access server config rendered, people in it: {files.people}\n"
        )


def _access_traffic_task(config: Config, secrets_dir: Path, data_dir: Path) -> list[BackgroundLoop]:
    """Counting what the people of the access server use; a box without one counts nobody."""
    if not config.access.enabled:
        return []
    count = partial(
        watch_traffic, data_dir / ACCESS_TRAFFIC_DIR, read=partial(access_samples, secrets_dir)
    )
    return [BackgroundLoop("access traffic counter", count)]


def _ddns_task(
    config: Config, box_state: BoxState, secrets_dir: Path, data_dir: Path
) -> list[BackgroundLoop]:
    """The name that follows the public address; it reads the live config every round."""
    if not config.ddns.enabled:
        return []
    watch = partial(watch_ddns, lambda: box_state.config, secrets_dir, data_dir / DDNS_STATE_FILE)
    return [BackgroundLoop("ddns", watch)]


def _telegram_bot(
    config: Config,
    config_path: Path,
    box_state: BoxState,
    resolver: Resolver | None,
    watchers: UplinkWatchers,
    inbox: deque[Event],
    secrets_dir: Path,
    data_dir: Path,
) -> TelegramBot:
    """The Telegram bot runs on every box and speaks once ``telegram.enabled`` and a linked chat
    say so; it finds Telegram where AdGuard finds names, when the box has AdGuard, and speaks the
    language of the panel."""
    try:
        return TelegramBot(
            lambda: box_state.config,
            secrets_dir=secrets_dir,
            data_dir=data_dir,
            catalog=load_catalog(config_path.parent / LOCALES_DIR, config.ui.language),
            lookup=resolver_lookup(resolver) if resolver is not None else system_lookup(),
            inbox=inbox,
            watchers=watchers,
        )
    except TelegramError as exc:  # VIBEDPN_TELEGRAM_API of a test stand that is not a URL
        sys.stderr.write(f"vibedpn-core: cannot start: {exc}\n")
        raise SystemExit(os.EX_CONFIG) from None


def _consumer_task(
    config: Config, box_state: BoxState, consumer: ConsumerStatus, secrets_dir: Path
) -> list[BackgroundLoop]:
    """The dpn consumer round on a box with a LAN; it idles while uplink dpn is off."""
    if config.network is None:
        return []
    step = consumer_round(secrets_dir)
    watch = partial(watch_consumer, lambda: box_state.config, consumer, step)
    return [BackgroundLoop("dpn consumer", watch)]


def _list_task(
    box_state: BoxState, resolver: Resolver | None, lists: ListsStatus, data_dir: Path
) -> list[BackgroundLoop]:
    """The round of routing.lists, on a box whose resolver serves smart."""
    if resolver is None:
        return []
    cache = ListCache(data_dir / LISTS_DIR)
    fetch = http_fetch(list_client())
    watch = partial(watch_lists, lambda: box_state.config, resolver, cache, fetch, lists)
    return [BackgroundLoop("domain lists", watch)]


def _report(what: str, written: bool | None) -> None:
    if written is not None:
        state = "updated" if written else "already current"
        sys.stderr.write(f"vibedpn-core: {what} configuration {state}\n")


def _render_lan_services(config: Config, secrets_dir: Path) -> None:
    """dnsmasq and hostapd of gateway mode, rendered before the API like AdGuard."""
    _report("dnsmasq", _write_dnsmasq(config))
    try:
        written = hostapd.ensure_hostapd(config, hostapd.core_dir(), secrets_dir)
    except hostapd.HostapdError as exc:
        sys.stderr.write(f"vibedpn-core: cannot start: {exc}\n")
        raise SystemExit(os.EX_CONFIG) from None
    _report("hostapd", written)


def _write_dnsmasq(config: Config) -> bool | None:
    """Before the API, like AdGuard: compose starts dnsmasq only once core is healthy."""
    try:
        written = ensure_dnsmasq(config, core_dir())
    except DnsmasqError as exc:
        sys.stderr.write(f"vibedpn-core: cannot start: {exc}\n")
        raise SystemExit(os.EX_CONFIG) from None
    return written


def _hand_adguard_dirs(config: Config, conf_dir: Path) -> None:
    """AdGuard runs as ADGUARD_UID: its config and working directory must be that user's."""
    if config.network is None or not config.dns.enabled:
        return
    work_dir = Path(os.environ.get(ADGUARD_WORK_DIR_ENV, DEFAULT_ADGUARD_WORK_DIR))
    try:
        give_to_adguard([conf_dir, work_dir], ADGUARD_UID)
    except AdguardError as exc:
        sys.stderr.write(f"vibedpn-core: cannot start: {exc}\n")
        raise SystemExit(os.EX_CONFIG) from None


def _resolver(config: Config) -> Resolver | None:
    """The resolver of routing.mode smart runs on every LAN box with AdGuard: the mode switches
    live, and until smart AdGuard simply does not ask it."""
    if config.network is None or not config.dns.enabled:
        return None
    client = httpx.Client(timeout=UPSTREAM_TIMEOUT_SECONDS, trust_env=False)
    return Resolver(RuleIndex.from_config(config), doh_exchange(list(config.dns.upstreams), client))


def _apply_with_resolver(resolver: Resolver | None) -> Callable[[Config], list[str]]:
    """Applying the router rebuilds its table and empties the channel sets: refill them at once."""

    def apply(config: Config) -> list[str]:
        uplinks = apply_router(config)
        if resolver is not None:
            resolver.reload(config)
        return uplinks

    return apply


def _box_state(
    config: Config,
    config_path: Path,
    watchers: UplinkWatchers,
    secrets_dir: Path,
    data_dir: Path,
) -> tuple[BoxState, Resolver | None, SmartLoop | None, ListsStatus]:
    """The live configuration, with the resolver of smart refilled after every router apply, and
    the DNS journal with its learner, and the status of routing.lists."""
    resolver = _resolver(config)
    state = BoxState(config, config_path, apply=_apply_with_resolver(resolver), watchers=watchers)
    smart = _smart_loop(config, state, resolver, secrets_dir, data_dir)
    return state, resolver, smart, ListsStatus()


def _smart_loop(
    config: Config,
    box_state: BoxState,
    resolver: Resolver | None,
    secrets_dir: Path,
    data_dir: Path,
) -> SmartLoop | None:
    """The DNS journal and the learner of routing.mode smart, on a box with AdGuard."""
    if resolver is None:
        return None
    try:
        store = LearnedStore(data_dir / LEARNED_FILE)
    except LearnedError as exc:
        sys.stderr.write(f"vibedpn-core: cannot start: {exc}\n")
        raise SystemExit(os.EX_CONFIG) from None
    return SmartLoop(
        lambda: box_state.config,
        resolver,
        store,
        DnsJournal(),
        querylog_fetcher(config, secrets_dir),
    )


def _lan_stores(
    config: Config, data_dir: Path
) -> tuple[DeviceStore | None, EventStore | None, Journal]:
    """The device store and the event journal of a box with a LAN; nothing to keep otherwise."""
    if config.network is None:
        return None, None, ignore_event
    try:
        devices = DeviceStore(data_dir / DB_FILE)
        events = EventStore(data_dir / EVENTS_FILE)
    except (DeviceError, EventError) as exc:
        sys.stderr.write(f"vibedpn-core: cannot start: {exc}\n")
        raise SystemExit(os.EX_CONFIG) from None
    return devices, events, store_journal(events)


def _watchers(config: Config, uplinks: Sequence[str], journal: Journal) -> UplinkWatchers:
    """A watcher for every uplink the router just put in use; state changes go to the journal."""
    table = uplink_table(config)
    return UplinkWatchers({key: table[key] for key in uplinks}, journal=journal)
