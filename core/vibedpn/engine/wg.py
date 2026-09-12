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
import os
import re
import secrets
import subprocess
import tempfile
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from ipaddress import IPv4Address, IPv4Interface
from pathlib import Path
from typing import Literal

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from vibedpn.config import Config, WgServerConfig
from vibedpn.detect import find_tool
from vibedpn.templating import template_environment

KEY_BYTES = 32
SERVER_DIR = "wg-server"  # under secrets/; compose.yaml mounts it into wg-server as /etc/wireguard
SERVER_KEY_FILE = "server.key"
SERVER_CONF_FILE = "wg0.conf"  # the name the wg image entrypoint reads
PEERS_FILE = "peers.json"
SERVER_TEMPLATE = "wg-server.conf.j2"
CLIENT_TEMPLATE = "wg-client.conf.j2"
DIR_MODE = 0o700
FILE_MODE = 0o600
# A peer name ends up in file names, comments and the CLI: keep it boring.
PEER_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
# A home box sends everything through its uplink, and sits behind NAT, so it keeps the mapping.
CLIENT_ALLOWED_IPS = "0.0.0.0/0"
CLIENT_KEEPALIVE_SECONDS = 25
WG = "wg"
WG_INTERFACE = "wg0"
DUMP_PEER_FIELDS = 8  # public key, psk, endpoint, allowed ips, handshake, rx, tx, keepalive
NO_VALUE = "(none)"

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
    subnet = _server_config(config).subnet
    return IPv4Interface(f"{next(subnet.hosts())}/{subnet.prefixlen}")


def render_server_conf(config: Config, private_key: str, peers: Sequence[Peer] = ()) -> str:
    template = template_environment().get_template(SERVER_TEMPLATE)
    return template.render(
        address=server_address(config),
        listen_port=_server_config(config).listen_port,
        private_key=private_key,
        peers=peers,
    )


def render_client_conf(config: Config, server_public_key: str, peer: Peer) -> str:
    """The file a home box installs with ``vibedpn init --role client --peer-config``."""
    server = _server_config(config)
    template = template_environment().get_template(CLIENT_TEMPLATE)
    return template.render(
        peer=peer,
        server_public_key=server_public_key,
        endpoint=f"{server.endpoint}:{server.listen_port}",
        allowed_ips=CLIENT_ALLOWED_IPS,
        keepalive=CLIENT_KEEPALIVE_SECONDS,
    )


def write_private(path: Path, content: str) -> bool:
    """Write a secret atomically with mode 600; ``False`` when the file already says exactly that.

    The temporary file is created 600 in the same directory, flushed to disk and renamed over the
    target, so a reader — the wg-server container — never sees a half-written key or config, and
    a power cut never leaves an empty one.
    """
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        path.chmod(FILE_MODE)
        return False
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), FILE_MODE)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary).replace(path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    fsync_directory(path.parent)
    return True


def fsync_directory(directory: Path) -> None:
    """Make a rename durable. ext4 flushes a rename onto an existing name early, but not one onto
    a new name — the very first server.key — so a power cut right after the first start could
    leave an empty key that core then refuses to replace."""
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def load_or_create_server_key(directory: Path) -> tuple[str, bool]:
    """The persisted server key, generated on first use; ``True`` when it was just created.

    A key file that exists but does not decode is an error, never a reason to make a new one:
    replacing the key would silently disconnect every home box.
    """
    path = directory / SERVER_KEY_FILE
    if path.exists():
        try:
            key = path.read_text(encoding="utf-8").strip()
            decode_key(key)
        except (OSError, UnicodeDecodeError, WgError) as exc:
            raise WgError(
                f"{path} is unreadable or not a WireGuard key ({exc}); restore it from a backup —"
                " a new key would disconnect every home box"
            ) from None
        path.chmod(FILE_MODE)
        return key, False
    key = generate_private_key()
    write_private(path, key + "\n")
    return key, True


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


def save_peers(directory: Path, peers: Sequence[Peer]) -> None:
    registry = PeerRegistry(peers=list(peers))
    write_private(directory / PEERS_FILE, registry.model_dump_json(indent=2) + "\n")


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


def ensure_server(config: Config, secrets_dir: Path) -> Path | None:
    """Key and ``wg0.conf`` of the VPS server; ``None`` when this configuration runs none."""
    if config.wg_server is None:
        return None
    with _REGISTRY_LOCK:
        return _render(config, _ensure_directory(secrets_dir))


def list_peers(config: Config, secrets_dir: Path) -> list[Peer]:
    _server_config(config)
    return load_peers(secrets_dir / SERVER_DIR)


def find_peer(config: Config, secrets_dir: Path, name: str) -> Peer:
    for peer in list_peers(config, secrets_dir):
        if peer.name == name:
            return peer
    raise PeerNotFoundError(f"no peer named {name!r}")


def add_peer(config: Config, secrets_dir: Path, name: str, now: datetime | None = None) -> Peer:
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
        )
        save_peers(directory, [*peers, peer])
        _render(config, directory)
    return peer


def remove_peer(config: Config, secrets_dir: Path, name: str) -> Peer:
    with _REGISTRY_LOCK:
        directory = _ensure_directory(secrets_dir)
        peers = load_peers(directory)
        removed = next((peer for peer in peers if peer.name == name), None)
        if removed is None:
            raise PeerNotFoundError(f"no peer named {name!r}")
        save_peers(directory, [peer for peer in peers if peer.name != name])
        _render(config, directory)
    return removed


def peer_config(config: Config, secrets_dir: Path, name: str) -> str:
    peer = find_peer(config, secrets_dir, name)
    key, _ = load_or_create_server_key(secrets_dir / SERVER_DIR)
    return render_client_conf(config, public_key(key), peer)


def parse_wg_dump(text: str) -> dict[str, PeerLink]:
    """``wg show <iface> dump``: tab-separated; the first line is the interface itself — with
    its private key, which is skipped and never kept — then one line per peer."""
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
    """Live state of the server interface; ``None`` when it cannot be read (no ``wg``, no wg0).

    core shares the host network namespace with wg-server, so it sees the same interface.
    """
    wg = find_tool(WG)
    if wg is None:
        return None
    try:
        probe = subprocess.run(
            [wg, "show", interface, "dump"], check=False, capture_output=True, text=True
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


def _render(config: Config, directory: Path) -> Path:
    try:
        key, _ = load_or_create_server_key(directory)
        conf = directory / SERVER_CONF_FILE
        write_private(conf, render_server_conf(config, key, load_peers(directory)))
    except OSError as exc:
        raise WgError(f"cannot write the tunnel files in {directory}: {exc.strerror}") from exc
    return conf
