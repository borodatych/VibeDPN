"""WireGuard keys, the peer registry and the rendered ``.conf`` files of the VPS server.

``core`` owns the server key: it is generated once, kept in ``secrets/wg-server/server.key``
and never rotated behind the owner's back, because every home box trusts exactly that public
key. Peers — home boxes — live in ``secrets/wg-server/peers.json``, written only by core.
``wg0.conf`` is derived from ``config.yaml``, the key and the registry, at every start and after
every peer change; the wg-server container applies a changed file on its own.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import secrets
import subprocess
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from ipaddress import IPv4Address, IPv4Interface
from pathlib import Path
from typing import Literal

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from vibedpn.atomic import FILE_MODE, write_private
from vibedpn.config import (
    AWG_DEFAULT_HEADERS,
    AWG_HANDSHAKE_BYTES,
    AWG_MAX_WIRE_BYTES,
    AwgConfig,
    Config,
    WgServerConfig,
)
from vibedpn.detect import find_tool
from vibedpn.templating import template_environment

KEY_BYTES = 32
SERVER_DIR = "wg-server"  # under secrets/; compose.yaml mounts it into wg-server as /etc/wireguard
SERVER_KEY_FILE = "server.key"
SERVER_CONF_FILE = "wg0.conf"  # the name the wg image entrypoint reads
# The 32-byte key that protects the AmneziaWG headers: both ends must hold it, so it is a secret
# of the server next to the server key and travels only inside the peer files.
HEADER_KEY_FILE = "header-protection.key"
PEERS_FILE = "peers.json"
SERVER_TEMPLATE = "wg-server.conf.j2"
CLIENT_TEMPLATE = "wg-client.conf.j2"
DIR_MODE = 0o700
# A peer name ends up in file names, comments and the CLI: keep it boring.
PEER_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
# A home box sends everything through its uplink, and sits behind NAT, so it keeps the mapping.
CLIENT_ALLOWED_IPS = "0.0.0.0/0"
CLIENT_KEEPALIVE_SECONDS = 25
AWG = "awg"  # the tool of AmneziaWG; it reads a plain WireGuard interface the same way
WG_INTERFACE = "wg0"
DUMP_PEER_FIELDS = 8  # public key, psk, endpoint, allowed ips, handshake, rx, tx, keepalive
NO_VALUE = "(none)"
RESERVED_ADDRESSES = 3  # the network, the broadcast and the server address
# What `awg enable` and `init` pick (amnezia.md, "параметры"): the documentation recommends 4-12
# junk packets; their sizes stay well below the MTU. Every data packet grows by S4 bytes, so the
# paddings stay small, and each message type gets a size of its own on the wire.
AWG_JUNK_COUNT = (4, 12)
AWG_JUNK_MIN_SIZE = (40, 100)
AWG_JUNK_SPREAD = (50, 400)
AWG_PADDING = (15, 64)

# FastAPI runs synchronous handlers in a thread pool: two requests must not interleave the
# read-modify-write of the registry.
_REGISTRY_LOCK = threading.Lock()


class WgError(RuntimeError):
    """A user-facing reason why the tunnel files could not be read or written."""


class PeerNameError(WgError):
    """The name does not fit ``PEER_NAME``."""


class PeerExistsError(WgError):
    """A peer with this name is already registered."""


class PeerNotFoundError(WgError):
    """No peer with this name."""


class SubnetFullError(WgError):
    """Every address of ``wg_server.subnet`` is taken."""


class Peer(BaseModel):
    """One home box as the server knows it. The private key is kept so ``export`` can repeat the
    peer file; it never leaves core except inside that file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    address: IPv4Address
    public_key: str
    private_key: str
    created: datetime
    # Only the tunnel subnet goes through the tunnel: a laptop or phone that needs the node
    # panel, not a home box that sends everything through its VPS.
    tunnel_only: bool = False


class PeerRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    peers: list[Peer] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_unique(self) -> PeerRegistry:
        names = [peer.name for peer in self.peers]
        addresses = [peer.address for peer in self.peers]
        if len(set(names)) != len(names) or len(set(addresses)) != len(addresses):
            raise ValueError("a peer name or address appears twice")
        return self


@dataclass(frozen=True)
class PeerLink:
    """What the running interface knows about a peer; ``latest_handshake`` 0 means never."""

    endpoint: str | None
    latest_handshake: int
    rx_bytes: int
    tx_bytes: int


@dataclass(frozen=True)
class Renumbered:
    """A peer moved into ``wg_server.subnet`` after the owner changed it."""

    name: str
    old: IPv4Address
    new: IPv4Address


@dataclass(frozen=True)
class ServerFiles:
    conf: Path
    renumbered: tuple[Renumbered, ...] = ()


def clamp(raw: bytes) -> bytes:
    """Curve25519 scalar clamping (RFC 7748 §5), what ``wg genkey`` applies to random bytes.

    X25519 clamps internally anyway; clamping before storing makes the key file byte-identical
    to one produced by ``wg genkey``, so the two tools can be swapped freely.
    """
    scalar = bytearray(raw)
    scalar[0] &= 248
    scalar[31] &= 127
    scalar[31] |= 64
    return bytes(scalar)


def generate_private_key() -> str:
    return base64.b64encode(clamp(secrets.token_bytes(KEY_BYTES))).decode("ascii")


def decode_key(text: str) -> bytes:
    """A WireGuard key is 32 bytes in standard base64 (44 characters with padding)."""
    try:
        raw = base64.b64decode(text.strip(), validate=True)
    except binascii.Error as exc:
        raise WgError("not a base64 WireGuard key") from exc
    if len(raw) != KEY_BYTES:
        raise WgError(f"a WireGuard key is {KEY_BYTES} bytes, this one is {len(raw)}")
    return raw


def public_key(private_key: str) -> str:
    raw = X25519PrivateKey.from_private_bytes(decode_key(private_key)).public_key()
    return base64.b64encode(raw.public_bytes_raw()).decode("ascii")


def server_address(config: Config) -> IPv4Interface:
    """The server takes the first host of ``wg_server.subnet``: 10.78.0.0/24 → 10.78.0.1/24."""
    server = _server_config(config)
    return IPv4Interface(f"{server.address}/{server.subnet.prefixlen}")


def _pick(bounds: tuple[int, int]) -> int:
    return secrets.choice(range(bounds[0], bounds[1] + 1))


def generate_awg() -> AwgConfig:
    """Random obfuscation parameters inside the bounds of amnezia.md, every handshake message of
    its own size on the wire (Init 148+S1, Response 92+S2, Cookie 64+S3) so a receiver cannot
    mistake one for another by length. Header protection keeps the standard message types."""
    junk_min = _pick(AWG_JUNK_MIN_SIZE)
    junk_max = min(junk_min + _pick(AWG_JUNK_SPREAD), AWG_MAX_WIRE_BYTES)
    while True:
        s1, s2, s3, s4 = (_pick(AWG_PADDING) for _ in range(4))
        sizes = {
            base + padding for base, padding in zip(AWG_HANDSHAKE_BYTES, (s1, s2, s3), strict=True)
        }
        if len(sizes) == len(AWG_HANDSHAKE_BYTES):
            break
    h1, h2, h3, h4 = AWG_DEFAULT_HEADERS
    return AwgConfig(
        jc=_pick(AWG_JUNK_COUNT),
        jmin=junk_min,
        jmax=junk_max,
        s1=s1,
        s2=s2,
        s3=s3,
        s4=s4,
        h1=h1,
        h2=h2,
        h3=h3,
        h4=h4,
    )


def render_server_conf(
    config: Config,
    private_key: str,
    peers: Sequence[Peer] = (),
    header_key: str | None = None,
) -> str:
    server = _server_config(config)
    template = template_environment().get_template(SERVER_TEMPLATE)
    return template.render(
        address=server_address(config),
        listen_port=server.listen_port,
        private_key=private_key,
        peers=peers,
        awg=server.awg,
        header_key=header_key,
    )


def render_client_conf(
    config: Config, server_public_key: str, peer: Peer, header_key: str | None = None
) -> str:
    """The file a home box installs with ``vibedpn init --role client --peer-config``, or a phone
    or laptop imports into its AmneziaWG app."""
    server = _server_config(config)
    template = template_environment().get_template(CLIENT_TEMPLATE)
    return template.render(
        peer=peer,
        server_public_key=server_public_key,
        awg=server.awg,
        header_key=header_key,
        endpoint=f"{server.endpoint}:{server.listen_port}",
        allowed_ips=str(server.subnet) if peer.tunnel_only else CLIENT_ALLOWED_IPS,
        keepalive=CLIENT_KEEPALIVE_SECONDS,
    )


def load_server_key(directory: Path) -> str:
    """The persisted server key, read only. A peer file made with a key the running server does
    not have would never handshake, so a missing key is an error here, never a new key."""
    path = directory / SERVER_KEY_FILE
    if not path.exists():
        raise WgError(f"{path} is missing; core creates the server key at start (vibedpn restart)")
    try:
        key = path.read_text(encoding="utf-8").strip()
        decode_key(key)
    except (OSError, UnicodeDecodeError, WgError) as exc:
        raise WgError(
            f"{path} is unreadable or not a WireGuard key ({exc}); restore it from a backup —"
            " a new key would disconnect every home box"
        ) from None
    return key


def load_or_create_server_key(directory: Path) -> tuple[str, bool]:
    """The persisted server key, generated on first use; ``True`` when it was just created.

    A key file that exists but does not decode is an error, never a reason to make a new one:
    replacing the key would silently disconnect every home box.
    """
    path = directory / SERVER_KEY_FILE
    if path.exists():
        key = load_server_key(directory)
        path.chmod(FILE_MODE)
        return key, False
    key = generate_private_key()
    write_private(path, key + "\n")
    return key, True


def load_header_key(directory: Path) -> str:
    """The persisted header protection key, read only: a peer file made without it never
    handshakes with the running server."""
    path = directory / HEADER_KEY_FILE
    try:
        key = path.read_text(encoding="utf-8").strip()
        decode_key(key)
    except (OSError, UnicodeDecodeError, WgError) as exc:
        raise WgError(
            f"{path} is missing or not a key ({exc.__class__.__name__}); core creates it at start"
            " (vibedpn restart)"
        ) from None
    return key


def sync_header_key(config: Config, directory: Path) -> str | None:
    """The header protection key of a server with obfuscation, created on first use; ``None``
    without it, and then a key left from an earlier obfuscation is removed so that enabling it
    again starts a new one. It is generated like a WireGuard key, clamped: the redaction of
    secrets in logs recognises exactly that shape of a base64 key (engine/logs.py)."""
    path = directory / HEADER_KEY_FILE
    if _server_config(config).awg is None:
        path.unlink(missing_ok=True)
        return None
    if path.exists():
        path.chmod(FILE_MODE)
        return load_header_key(directory)
    key = generate_private_key()
    write_private(path, key + "\n")
    return key


def load_peers(directory: Path) -> list[Peer]:
    """The registry; empty when there is none yet. A damaged file is an error, never a reset:
    dropping it would disconnect every home box on the next render."""
    path = directory / PEERS_FILE
    if not path.exists():
        return []
    try:
        registry = PeerRegistry.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, ValueError, ValidationError) as exc:
        raise WgError(
            f"{path} is damaged ({exc.__class__.__name__}); restore it from a backup"
        ) from None
    return registry.peers


def check_peer_name(name: str) -> str:
    if PEER_NAME.fullmatch(name) is None:
        raise PeerNameError(
            f"{name!r} is not a peer name: 1-32 lowercase letters, digits and hyphens,"
            " starting with a letter or digit"
        )
    return name


def next_address(config: Config, peers: Sequence[Peer]) -> IPv4Address:
    """The lowest free host of the subnet; the server keeps the first one."""
    taken = {server_address(config).ip, *(peer.address for peer in peers)}
    for host in _server_config(config).subnet.hosts():
        if host not in taken:
            return host
    raise SubnetFullError(
        f"every address of wg_server.subnet {_server_config(config).subnet} is taken;"
        " remove a peer or widen the subnet"
    )


def fit_to_subnet(
    config: Config, peers: Sequence[Peer]
) -> tuple[list[Peer], tuple[Renumbered, ...]]:
    """Peers whose address does not belong to ``wg_server.subnet`` any more — the owner changed
    it — move to free addresses of the new subnet and keep their keys and names.

    Refusing to start instead would leave the owner without the API, so without ``vibedpn peer``
    to fix it; moved boxes only need their file exported again. A subnet too small for every
    peer is a configuration error the owner fixes in ``config.yaml``.
    """
    subnet = _server_config(config).subnet
    server_ip = server_address(config).ip
    outside = {subnet.network_address, subnet.broadcast_address, server_ip}
    kept: list[Peer] = []
    for peer in peers:
        if peer.address in subnet and peer.address not in outside:
            kept.append(peer)
    kept_names = {peer.name for peer in kept}
    placed: list[Peer] = []
    taken = list(kept)
    moved: list[Renumbered] = []
    for peer in peers:
        if peer.name in kept_names:
            placed.append(peer)
            continue
        try:
            address = next_address(config, taken)
        except SubnetFullError:
            capacity = max(0, subnet.num_addresses - RESERVED_ADDRESSES)
            raise WgError(
                f"wg_server.subnet {subnet} has room for {capacity} peers, the registry has"
                f" {len(peers)}; choose a wider subnet in config.yaml"
            ) from None
        moved_peer = peer.model_copy(update={"address": address})
        taken.append(moved_peer)
        placed.append(moved_peer)
        moved.append(Renumbered(peer.name, peer.address, address))
    return placed, tuple(moved)


def ensure_server(config: Config, secrets_dir: Path) -> ServerFiles | None:
    """Key and ``wg0.conf`` of the VPS server; ``None`` when this configuration runs none."""
    if config.wg_server is None:
        return None
    with _REGISTRY_LOCK:
        directory = _ensure_directory(secrets_dir)
        return _commit(config, directory, load_peers(directory))


def list_peers(config: Config, secrets_dir: Path) -> list[Peer]:
    _server_config(config)
    return load_peers(secrets_dir / SERVER_DIR)


def find_peer(config: Config, secrets_dir: Path, name: str) -> Peer:
    for peer in list_peers(config, secrets_dir):
        if peer.name == name:
            return peer
    raise PeerNotFoundError(f"no peer named {name!r}")


def add_peer(
    config: Config,
    secrets_dir: Path,
    name: str,
    now: datetime | None = None,
    *,
    tunnel_only: bool = False,
) -> Peer:
    """Register a home box: a fresh key pair and the next free address, then re-render."""
    check_peer_name(name)
    with _REGISTRY_LOCK:
        directory = _ensure_directory(secrets_dir)
        peers = load_peers(directory)
        if any(peer.name == name for peer in peers):
            raise PeerExistsError(f"a peer named {name!r} already exists")
        private_key = generate_private_key()
        peer = Peer(
            name=name,
            address=next_address(config, peers),
            public_key=public_key(private_key),
            private_key=private_key,
            created=now or datetime.now(UTC),
            tunnel_only=tunnel_only,
        )
        _commit(config, directory, [*peers, peer])
    return peer


def remove_peer(config: Config, secrets_dir: Path, name: str) -> Peer:
    with _REGISTRY_LOCK:
        directory = _ensure_directory(secrets_dir)
        peers = load_peers(directory)
        removed = next((peer for peer in peers if peer.name == name), None)
        if removed is None:
            raise PeerNotFoundError(f"no peer named {name!r}")
        _commit(config, directory, [peer for peer in peers if peer.name != name])
    return removed


def peer_config(config: Config, secrets_dir: Path, name: str) -> str:
    peer = find_peer(config, secrets_dir, name)
    directory = secrets_dir / SERVER_DIR
    key = load_server_key(directory)
    header_key = load_header_key(directory) if _server_config(config).awg is not None else None
    return render_client_conf(config, public_key(key), peer, header_key)


def parse_wg_dump(text: str) -> dict[str, PeerLink]:
    """``awg show <iface> dump``: tab-separated; the first line is the interface itself — with its
    private key, which is skipped and never kept, and the obfuscation parameters, which no caller
    needs — then one line per peer, the same eight fields as ``wg show`` prints."""
    links: dict[str, PeerLink] = {}
    for line in text.splitlines()[1:]:
        fields = line.split("\t")
        if len(fields) < DUMP_PEER_FIELDS:
            continue
        key, _psk, endpoint, _allowed, handshake, rx, tx, _keepalive = fields[:DUMP_PEER_FIELDS]
        try:
            links[key] = PeerLink(
                endpoint=None if endpoint == NO_VALUE else endpoint,
                latest_handshake=int(handshake),
                rx_bytes=int(rx),
                tx_bytes=int(tx),
            )
        except ValueError:
            continue
    return links


def read_wg_dump(interface: str = WG_INTERFACE) -> dict[str, PeerLink] | None:
    """Live state of the server interface; ``None`` when it cannot be read (no ``awg``, no wg0).

    The interface is a TUN device of the daemon in wg-server, which listens on a socket in a
    directory both containers mount (compose.yaml): that socket is what ``awg`` talks to.
    """
    awg = find_tool(AWG)
    if awg is None:
        return None
    try:
        probe = subprocess.run(
            [awg, "show", interface, "dump"], check=False, capture_output=True, text=True
        )
    except OSError:
        return None
    if probe.returncode != 0:
        return None
    return parse_wg_dump(probe.stdout)


def _server_config(config: Config) -> WgServerConfig:
    if config.wg_server is None:
        raise WgError("this configuration runs no WireGuard server")
    return config.wg_server


def _ensure_directory(secrets_dir: Path) -> Path:
    directory = secrets_dir / SERVER_DIR
    try:
        directory.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
        directory.chmod(DIR_MODE)
    except OSError as exc:
        raise WgError(f"cannot write the tunnel files in {directory}: {exc.strerror}") from exc
    return directory


def _commit(config: Config, directory: Path, peers: Sequence[Peer]) -> ServerFiles:
    """Write ``wg0.conf`` and the registry as one change.

    The config goes first and is put back when the registry cannot be saved: the running server
    never keeps a peer the registry lost, and a retried ``peer add`` never meets a name that is
    registered but missing from the server.
    """
    conf = directory / SERVER_CONF_FILE
    try:
        key, _ = load_or_create_server_key(directory)
        placed, renumbered = fit_to_subnet(config, peers)
        previous = conf.read_text(encoding="utf-8") if conf.is_file() else None
        header_key = sync_header_key(config, directory)
        write_private(conf, render_server_conf(config, key, placed, header_key))
        try:
            registry = PeerRegistry(peers=placed)
            write_private(directory / PEERS_FILE, registry.model_dump_json(indent=2) + "\n")
        except BaseException:
            if previous is None:
                conf.unlink(missing_ok=True)
            else:
                write_private(conf, previous)
            raise
    except OSError as exc:
        raise WgError(f"cannot write the tunnel files in {directory}: {exc.strerror}") from exc
    return ServerFiles(conf=conf, renumbered=renumbered)
