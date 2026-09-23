"""The access server: VLESS over REALITY for the owner's people (decision 30).

core owns the key of the server and the list of people — ``secrets/access/server.json`` and
``secrets/access/people.json``, written only here. From them and ``config.yaml`` it renders what the
server reads into its data directory: ``config.json`` (the whole Xray configuration, read at start),
``people.tsv`` (the people, which the entrypoint applies through the API of Xray without a restart),
``person.json`` (what the entrypoint fills with one person for ``xray api adu``) and ``health.json``
(the client its health check connects to itself with). The server is not root, so that directory
and its files belong to its uid and keep the mode of a secret.

REALITY keys are X25519 — the curve of WireGuard — in base64url without padding, so core makes them
itself. A share link is built here and read back by the client side (engine/xray.py): a link our own
uplink cannot parse is a link no phone should get.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import secrets
import threading
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlencode

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from vibedpn.atomic import write_private
from vibedpn.config import Config
from vibedpn.engine.router import ACCESS_UID, EGRESS_BLOCKED_RANGES
from vibedpn.engine.wg import KEY_BYTES, PEER_NAME, clamp

SECRETS_SUBDIR = "access"  # under secrets/: the key and the list of people, root's only
SERVER_FILE = "server.json"
PEOPLE_FILE = "people.json"
# What the server reads, in its data directory (compose.yaml mounts it into the access service).
CONFIG_FILE = "config.json"
PEOPLE_TABLE_FILE = "people.tsv"
PERSON_TEMPLATE_FILE = "person.json"
HEALTH_FILE = "health.json"
# The fields images/xray/entrypoint.sh replaces in person.json; names and ids never contain them.
TEMPLATE_ID = "@ID@"
TEMPLATE_EMAIL = "@EMAIL@"
DIR_MODE = 0o700
# The inbound of the people; images/xray/entrypoint.sh adds and removes them by this tag.
INBOUND_TAG = "people"
# Loopback ports of the server: its API (people on the fly), its counters (/debug/vars) and the
# client of its health check. images/xray/entrypoint.sh uses the same numbers.
API_PORT = 4481
METRICS_PORT = 4482
HEALTH_PORT = 4483
FLOW = "xtls-rprx-vision"
# How the links tell a phone to shake hands: "randomized" picks curves the server does not take
# and the handshake never completes (knowledge xray/realityServer.md).
FINGERPRINT = "chrome"
TARGET_PORT = 443  # the cover site is an HTTPS site
SHORT_ID_BYTES = 8
# The service user of the health check: a leading underscore no person's name can have.
HEALTH_EMAIL = "_health"
# Where a person never goes through the box: its loopback (core trusts its API there), the networks
# around the box, and addresses that are not the internet at all.
BLOCKED_RANGES = (
    "0.0.0.0/8",
    "127.0.0.0/8",
    *EGRESS_BLOCKED_RANGES,
    "::1/128",
    "fc00::/7",
    "fe80::/10",
)

_LOCK = threading.Lock()


class AccessError(RuntimeError):
    """A user-facing reason the access server or its list of people cannot be changed."""


class PersonNameError(AccessError):
    pass


class PersonExistsError(AccessError):
    pass


class PersonNotFoundError(AccessError):
    pass


class ServerKeys(BaseModel):
    """What makes the server itself: generated once and never rotated behind the owner's back,
    because every link handed out carries the public half and the short id."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1] = 1
    private_key: str
    short_id: str
    health_id: str  # the id of the service user of the health check


class Person(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    id: str  # the VLESS user id: what the link carries and the server checks
    created: datetime


class People(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    people: list[Person] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_unique(self) -> People:
        names = [person.name for person in self.people]
        ids = [person.id for person in self.people]
        if len(set(names)) != len(names) or len(set(ids)) != len(ids):
            raise ValueError("a name or an id appears twice")
        return self


@dataclass(frozen=True)
class AccessFiles:
    directory: Path
    people: int


def encode_key(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_key(text: str) -> bytes:
    """A REALITY key is 32 bytes in base64url without padding (43 characters)."""
    stripped = text.strip()
    try:
        raw = base64.urlsafe_b64decode(stripped + "=" * (-len(stripped) % 4))
    except (binascii.Error, ValueError) as exc:
        raise AccessError("not a base64url REALITY key") from exc
    if len(raw) != KEY_BYTES:
        raise AccessError(f"a REALITY key is {KEY_BYTES} bytes, this one is {len(raw)}")
    return raw


def generate_keys() -> ServerKeys:
    return ServerKeys(
        private_key=encode_key(clamp(secrets.token_bytes(KEY_BYTES))),
        short_id=secrets.token_hex(SHORT_ID_BYTES),
        health_id=str(uuid.uuid4()),
    )


def public_key(keys: ServerKeys) -> str:
    raw = X25519PrivateKey.from_private_bytes(decode_key(keys.private_key)).public_key()
    return encode_key(raw.public_bytes_raw())


def check_person_name(name: str) -> str:
    if PEER_NAME.fullmatch(name) is None:
        raise PersonNameError(
            f"{name!r} is not a name for a person: 1-32 lowercase letters, digits and hyphens,"
            " starting with a letter or digit"
        )
    return name


def dns_server(config: Config) -> str:
    """Where the server resolves names: the AdGuard of a box with a LAN — its answers fill the sets
    the rules of routing.mode smart steer by — and the resolver of the host everywhere else."""
    if config.network is not None and config.dns.enabled:
        return str(config.network.lan_address)
    return "localhost"


def render_server(config: Config, keys: ServerKeys, people: Sequence[Person]) -> str:
    """The Xray configuration of the server.

    Access logs are off: they would keep every site the people visit. The people's DNS goes to the
    resolver of the box, names in their TLS and HTTP are sniffed so a rule for a site applies to a
    phone that connects by address, and the box itself and the networks around it are closed to
    them. Only the service user of the health check reaches the counters on loopback.
    """
    clients = [
        {"id": keys.health_id, "email": HEALTH_EMAIL, "flow": FLOW},
        *({"id": person.id, "email": person.name, "flow": FLOW} for person in people),
    ]
    server = {
        "log": {"access": "none", "loglevel": "warning"},
        "api": {"tag": "api", "services": ["HandlerService", "StatsService"]},
        "stats": {},
        "policy": {"levels": {"0": {"statsUserUplink": True, "statsUserDownlink": True}}},
        "metrics": {"tag": "metrics", "listen": f"127.0.0.1:{METRICS_PORT}"},
        "dns": {"servers": [dns_server(config)], "queryStrategy": "UseIPv4", "tag": "dns-internal"},
        "inbounds": [
            {
                "tag": "api",
                "listen": "127.0.0.1",
                "port": API_PORT,
                "protocol": "dokodemo-door",
                "settings": {"address": "127.0.0.1"},
            },
            {
                "tag": INBOUND_TAG,
                "listen": "0.0.0.0",
                "port": config.access.port,
                "protocol": "vless",
                "settings": {"clients": clients, "decryption": "none"},
                "streamSettings": {
                    "network": "raw",
                    "security": "reality",
                    "realitySettings": {
                        "show": False,
                        "target": f"{config.access.target}:{TARGET_PORT}",
                        "serverNames": [config.access.target],
                        "privateKey": keys.private_key,
                        "shortIds": [keys.short_id],
                    },
                },
                "sniffing": {
                    "enabled": True,
                    "destOverride": ["http", "tls", "quic"],
                    "routeOnly": False,
                },
            },
        ],
        "outbounds": [
            {"tag": "direct", "protocol": "freedom", "settings": {"domainStrategy": "UseIPv4"}},
            {"tag": "dns-out", "protocol": "dns"},
            {"tag": "block", "protocol": "blackhole"},
        ],
        "routing": {
            # a name is resolved to be checked against the closed ranges: no name leads home
            "domainStrategy": "IPIfNonMatch",
            "rules": [
                {"inboundTag": ["api"], "outboundTag": "api"},
                {"inboundTag": ["dns-internal"], "outboundTag": "direct"},
                {"user": [HEALTH_EMAIL], "outboundTag": "direct"},
                {"inboundTag": [INBOUND_TAG], "port": "53", "outboundTag": "dns-out"},
                {"ip": list(BLOCKED_RANGES), "outboundTag": "block"},
            ],
        },
    }
    return json.dumps(server, indent=2, ensure_ascii=False) + "\n"


def render_health(config: Config, keys: ServerKeys) -> str:
    """The client of the health check: in through REALITY as the service user, out to the counters
    of the server on loopback. It passes only when the cover site lends its handshake."""
    client = {
        "log": {"access": "none", "loglevel": "warning"},
        "inbounds": [
            {
                "tag": "health",
                "listen": "127.0.0.1",
                "port": HEALTH_PORT,
                "protocol": "dokodemo-door",
                "settings": {"address": "127.0.0.1", "port": METRICS_PORT, "network": "tcp"},
            }
        ],
        "outbounds": [
            {
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {
                            "address": "127.0.0.1",
                            "port": config.access.port,
                            "users": [{"id": keys.health_id, "encryption": "none", "flow": FLOW}],
                        }
                    ]
                },
                "streamSettings": {
                    "network": "raw",
                    "security": "reality",
                    "realitySettings": {
                        "serverName": config.access.target,
                        "fingerprint": FINGERPRINT,
                        "publicKey": public_key(keys),
                        "shortId": keys.short_id,
                    },
                },
            }
        ],
    }
    return json.dumps(client, indent=2, ensure_ascii=False) + "\n"


def render_person_template(config: Config) -> str:
    """One person for ``xray api adu``: the API builds a whole inbound from it, so it needs the tag,
    the protocol and the port of the real one (without a port it adds nobody and still exits 0)."""
    inbound = {
        "tag": INBOUND_TAG,
        "protocol": "vless",
        "listen": "0.0.0.0",
        "port": config.access.port,
        "settings": {
            "clients": [{"id": TEMPLATE_ID, "email": TEMPLATE_EMAIL, "flow": FLOW}],
            "decryption": "none",
        },
    }
    return json.dumps({"inbounds": [inbound]}, indent=2) + "\n"


def render_people_table(people: Sequence[Person]) -> str:
    """One person a line, ``name<TAB>id``, sorted: what the entrypoint compares with the table it
    applied last and turns into ``xray api adu`` and ``rmu``."""
    return "".join(f"{person.name}\t{person.id}\n" for person in sorted(people, key=_by_name))


def share_link(config: Config, keys: ServerKeys, person: Person) -> str:
    """``vless://<id>@<address>:<port>?<params>#<name>`` — the form Xray publishes
    (https://github.com/XTLS/Xray-core/discussions/716) and phone apps import."""
    address = config.access_address()
    if address is None:
        raise AccessError("access.address is not set: the links would name no server")
    params = {
        "encryption": "none",
        "flow": FLOW,
        "security": "reality",
        "sni": config.access.target,
        "fp": FINGERPRINT,
        "pbk": public_key(keys),
        "sid": keys.short_id,
        "type": "tcp",
    }
    return (
        f"vless://{person.id}@{address}:{config.access.port}"
        f"?{urlencode(params)}#{quote(person.name, safe='')}"
    )


def load_keys(directory: Path) -> ServerKeys:
    path = directory / SERVER_FILE
    try:
        return ServerKeys.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        raise AccessError(
            "the access server has no key yet: it is made when the server is on"
        ) from None
    except (OSError, UnicodeDecodeError, ValueError, ValidationError) as exc:
        raise AccessError(
            f"{path} is damaged ({exc.__class__.__name__}); restore it from a backup —"
            " a new key would stop every link handed out"
        ) from None


def load_or_create_keys(directory: Path) -> ServerKeys:
    if not (directory / SERVER_FILE).exists():
        keys = generate_keys()
        write_private(directory / SERVER_FILE, keys.model_dump_json(indent=2) + "\n")
        return keys
    return load_keys(directory)


def load_people(directory: Path) -> list[Person]:
    """The list; empty when there is none yet. A damaged file is an error, never a reset: dropping
    it would cut off every person on the next render."""
    path = directory / PEOPLE_FILE
    if not path.exists():
        return []
    try:
        return People.model_validate(json.loads(path.read_text(encoding="utf-8"))).people
    except (OSError, UnicodeDecodeError, ValueError, ValidationError) as exc:
        raise AccessError(
            f"{path} is damaged ({exc.__class__.__name__}); restore it from a backup"
        ) from None


def ensure_access(
    config: Config, secrets_dir: Path, data_dir: Path, *, owner: int | None = ACCESS_UID
) -> AccessFiles | None:
    """The key and the files of the server; ``None`` when this configuration runs none."""
    if not config.access.enabled:
        return None
    with _LOCK:
        directory = _secrets_directory(secrets_dir)
        keys = load_or_create_keys(directory)
        people = load_people(directory)
        _render(config, keys, people, data_dir, owner)
    return AccessFiles(directory=data_dir, people=len(people))


def list_people(secrets_dir: Path) -> list[Person]:
    return load_people(secrets_dir / SECRETS_SUBDIR)


def find_person(secrets_dir: Path, name: str) -> Person:
    for person in list_people(secrets_dir):
        if person.name == name:
            return person
    raise PersonNotFoundError(f"no person named {name!r}")


def person_link(config: Config, secrets_dir: Path, name: str) -> str:
    person = find_person(secrets_dir, name)
    return share_link(config, load_keys(secrets_dir / SECRETS_SUBDIR), person)


def add_person(
    config: Config,
    secrets_dir: Path,
    data_dir: Path,
    name: str,
    now: datetime | None = None,
    *,
    owner: int | None = ACCESS_UID,
) -> tuple[Person, str]:
    """Register a person: a fresh id, the files of the server, and the link to hand them."""
    _check_on(config)
    check_person_name(name)
    with _LOCK:
        directory = _secrets_directory(secrets_dir)
        keys = load_or_create_keys(directory)
        people = load_people(directory)
        if any(person.name == name for person in people):
            raise PersonExistsError(f"a person named {name!r} already exists")
        person = Person(name=name, id=str(uuid.uuid4()), created=now or datetime.now(UTC))
        _commit(config, keys, directory, data_dir, people, [*people, person], owner)
    return person, share_link(config, keys, person)


def remove_person(
    config: Config,
    secrets_dir: Path,
    data_dir: Path,
    name: str,
    *,
    owner: int | None = ACCESS_UID,
) -> Person:
    _check_on(config)
    with _LOCK:
        directory = _secrets_directory(secrets_dir)
        keys = load_or_create_keys(directory)
        people = load_people(directory)
        removed = next((person for person in people if person.name == name), None)
        if removed is None:
            raise PersonNotFoundError(f"no person named {name!r}")
        remaining = [person for person in people if person.name != name]
        _commit(config, keys, directory, data_dir, people, remaining, owner)
    return removed


def _by_name(person: Person) -> str:
    return person.name


def _check_on(config: Config) -> None:
    if not config.access.enabled:
        raise AccessError("the access server is off: `vibedpn access enable` first")


def _secrets_directory(secrets_dir: Path) -> Path:
    directory = secrets_dir / SECRETS_SUBDIR
    try:
        directory.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
        directory.chmod(DIR_MODE)
    except OSError as exc:
        raise AccessError(f"cannot write the access files in {directory}: {exc.strerror}") from exc
    return directory


def _render(
    config: Config,
    keys: ServerKeys,
    people: Sequence[Person],
    data_dir: Path,
    owner: int | None,
) -> None:
    try:
        data_dir.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
        data_dir.chmod(DIR_MODE)
        if owner is not None:
            os.chown(data_dir, owner, owner)
        write_private(data_dir / CONFIG_FILE, render_server(config, keys, people), owner=owner)
        write_private(data_dir / HEALTH_FILE, render_health(config, keys), owner=owner)
        write_private(data_dir / PERSON_TEMPLATE_FILE, render_person_template(config), owner=owner)
        write_private(data_dir / PEOPLE_TABLE_FILE, render_people_table(people), owner=owner)
    except OSError as exc:
        raise AccessError(
            f"cannot write the files of the access server in {data_dir}: {exc.strerror}"
        ) from exc


def _commit(
    config: Config,
    keys: ServerKeys,
    directory: Path,
    data_dir: Path,
    previous: Sequence[Person],
    people: Sequence[Person],
    owner: int | None,
) -> None:
    """Render the server's files, then save the list; put the files back when the list cannot be
    saved. The running server never keeps a person the list lost, and a retried ``add`` never meets
    a name that is listed but missing from the server."""
    _render(config, keys, people, data_dir, owner)
    try:
        registry = People(people=list(people))
        write_private(directory / PEOPLE_FILE, registry.model_dump_json(indent=2) + "\n")
    except BaseException:
        _render(config, keys, previous, data_dir, owner)
        raise
