"""WireGuard keys and the rendered ``wg0.conf`` of the VPS server.

``core`` owns the server key: it is generated once, kept in ``secrets/wg-server/server.key``
and never rotated behind the owner's back, because every home box trusts exactly that public
key. ``wg0.conf`` is derived from ``config.yaml`` and the key at every start. Peers — their
registry, ``vibedpn peer add|rm|list|export`` — arrive in the next roadmap checkbox; the
renderer already takes them.
"""

from __future__ import annotations

import base64
import binascii
import os
import secrets
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Interface
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from vibedpn.config import Config
from vibedpn.templating import template_environment

KEY_BYTES = 32
SERVER_DIR = "wg-server"  # under secrets/; compose.yaml mounts it into wg-server as /etc/wireguard
SERVER_KEY_FILE = "server.key"
SERVER_CONF_FILE = "wg0.conf"  # the name the wg image entrypoint reads
SERVER_TEMPLATE = "wg-server.conf.j2"
DIR_MODE = 0o700
FILE_MODE = 0o600


class WgError(RuntimeError):
    """A user-facing reason why the tunnel files could not be read or written."""


@dataclass(frozen=True)
class Peer:
    """One home box as the server sees it: a name, its public key and its tunnel address."""

    name: str
    public_key: str
    address: IPv4Address


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
    if config.wg_server is None:
        raise WgError("this configuration runs no WireGuard server")
    subnet = config.wg_server.subnet
    return IPv4Interface(f"{next(subnet.hosts())}/{subnet.prefixlen}")


def render_server_conf(config: Config, private_key: str, peers: Sequence[Peer] = ()) -> str:
    if config.wg_server is None:
        raise WgError("this configuration runs no WireGuard server")
    template = template_environment().get_template(SERVER_TEMPLATE)
    return template.render(
        address=server_address(config),
        listen_port=config.wg_server.listen_port,
        private_key=private_key,
        peers=peers,
    )


def write_private(path: Path, content: str) -> bool:
    """Write a secret atomically with mode 600; ``False`` when the file already says exactly that.

    The temporary file is created 600 in the same directory and renamed over the target, so a
    reader — the wg-server container — never sees a half-written key or config.
    """
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        path.chmod(FILE_MODE)
        return False
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        Path(temporary).chmod(FILE_MODE)
        Path(temporary).replace(path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return True


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


def ensure_server(config: Config, secrets_dir: Path) -> Path | None:
    """Key and ``wg0.conf`` of the VPS server; ``None`` when this configuration runs none."""
    if config.wg_server is None:
        return None
    directory = secrets_dir / SERVER_DIR
    try:
        directory.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
        directory.chmod(DIR_MODE)
        key, _ = load_or_create_server_key(directory)
        conf = directory / SERVER_CONF_FILE
        write_private(conf, render_server_conf(config, key))
    except OSError as exc:
        raise WgError(f"cannot write the tunnel files in {directory}: {exc.strerror}") from exc
    return conf
