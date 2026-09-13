"""Change routing and device policies in ``config.yaml`` in place; comments and layout stay.

``config.yaml`` is the owner's file: rendering it again from the model would drop their own
comments and ordering. A round-trip load keeps both; the indentation matches the template, so
the diff of ``vibedpn mode full`` is one line. The result is validated with the full model before
it is written, and written atomically — core reads the file at start.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass
from ipaddress import IPv4Address
from pathlib import Path

from pydantic import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import YAMLError

from vibedpn.atomic import write_like
from vibedpn.config import (
    Config,
    DevicePolicy,
    NetworkConfig,
    RoutingMode,
    Upstream,
    normalize_mac,
    parse_yaml,
)

# The layout of templates/config.yaml.j2: lists indented under their key.
MAPPING_INDENT = 2
SEQUENCE_INDENT = 4
SEQUENCE_OFFSET = 2
NO_LINE_WRAP = 4096


class ConfigEditError(ValueError):
    """A user-facing reason why ``config.yaml`` was not changed."""


def round_trip_yaml() -> YAML:
    yaml = YAML(typ="rt", pure=True)
    yaml.preserve_quotes = True
    yaml.indent(mapping=MAPPING_INDENT, sequence=SEQUENCE_INDENT, offset=SEQUENCE_OFFSET)
    yaml.width = NO_LINE_WRAP
    # Round-trip dumps None as an empty value; files written by others (AdGuard spells out
    # `null`) must keep every key we do not own byte for byte.
    yaml.representer.add_representer(
        type(None), lambda dumper, _: dumper.represent_scalar("tag:yaml.org,2002:null", "null")
    )
    return yaml


def _first_problem(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or 'config'}: {error['msg']}"
        for error in exc.errors()
    )


Mutate = Callable[[CommentedMap], None]


def _edit(path: Path, mutate: Mutate) -> tuple[Config, bool]:
    """Load ``path`` round-trip, let ``mutate`` change the document, validate the result with the
    full model and write it atomically; nothing is written when the box would not be valid."""
    yaml = round_trip_yaml()
    try:
        data = yaml.load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigEditError(f"cannot read {path}: {exc.strerror or exc}") from exc
    except YAMLError as exc:
        raise ConfigEditError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(data, CommentedMap):
        raise ConfigEditError(f"{path}: the top level must be a mapping")
    mutate(data)
    buffer = io.StringIO()
    yaml.dump(data, buffer)
    new_text = buffer.getvalue()
    try:
        config = Config.model_validate(parse_yaml(new_text))
    except ValidationError as exc:
        raise ConfigEditError(f"config.yaml not changed: {_first_problem(exc)}") from None
    try:
        changed = write_like(path, new_text)
    except PermissionError:
        raise ConfigEditError(f"cannot write next to {path}; run with sudo") from None
    except OSError as exc:
        raise ConfigEditError(f"cannot write {path}: {exc.strerror or exc}") from exc
    return config, changed


def set_routing(
    path: Path, *, mode: RoutingMode | None = None, upstream: Upstream | None = None
) -> tuple[Config, bool]:
    """Set ``routing.mode`` and/or ``routing.default_upstream``; returns the validated result and
    whether the file changed. Nothing is written when the result would not be a valid box."""

    def mutate(data: CommentedMap) -> None:
        routing = data.get("routing")
        if not isinstance(routing, dict):
            raise ConfigEditError(
                f"{path} has no routing section: a box of this role routes no LAN"
            )
        if mode is not None:
            routing["mode"] = mode.value
        if upstream is not None:
            routing["default_upstream"] = upstream.value

    return _edit(path, mutate)


def set_vps_lan_access(path: Path, allowed: bool) -> tuple[Config, bool]:
    """Open or close the tunnel of the VPS uplink to the LAN (``upstreams.vps.lan_access``)."""

    def mutate(data: CommentedMap) -> None:
        upstreams = data.get("upstreams")
        vps = upstreams.get("vps") if isinstance(upstreams, dict) else None
        if not isinstance(vps, dict):
            raise ConfigEditError(f"{path} has no upstreams.vps section")
        vps["lan_access"] = allowed

    return _edit(path, mutate)


def set_dpn_country(path: Path, country: str | None) -> tuple[Config, bool]:
    """Pin uplink dpn to a country (ISO 3166-1 alpha-2), or let it take any (``None``)."""

    def mutate(data: CommentedMap) -> None:
        upstreams = data.get("upstreams")
        dpn = upstreams.get("dpn") if isinstance(upstreams, dict) else None
        if not isinstance(dpn, dict):
            raise ConfigEditError(f"{path} has no upstreams.dpn section")
        dpn["country"] = country

    return _edit(path, mutate)


def set_network(path: Path, network: NetworkConfig) -> tuple[Config, bool]:
    """Replace the keys of the ``network`` section; its comments and the rest of the file stay."""

    def mutate(data: CommentedMap) -> None:
        section = data.get("network")
        if not isinstance(section, CommentedMap):
            raise ConfigEditError(f"{path} has no network section: a box of this role has no LAN")
        values = network.model_dump(mode="json", exclude_none=True)
        for key in [key for key in section if key not in values]:
            del section[key]
        for key, value in values.items():
            section[key] = CommentedMap(value) if isinstance(value, dict) else value

    return _edit(path, mutate)


class DeviceNotFoundError(ConfigEditError):
    """``config.yaml`` has no device with this MAC or address."""


@dataclass(frozen=True)
class DeviceIdent:
    """A device named on the command line or in the API: by MAC, or by IPv4 address."""

    mac: str | None
    ip: IPv4Address | None

    @classmethod
    def parse(cls, text: str) -> DeviceIdent:
        try:
            return cls(normalize_mac(text), None)
        except ValueError:
            pass
        try:
            return cls(None, IPv4Address(text))
        except ValueError:
            raise ConfigEditError(f"{text!r} is neither a MAC nor an IPv4 address") from None

    def matches(self, entry: object) -> bool:
        if not isinstance(entry, dict):
            return False
        if self.mac is not None:
            try:
                return entry.get("mac") is not None and normalize_mac(str(entry["mac"])) == self.mac
            except ValueError:
                return False
        return entry.get("ip") is not None and str(entry["ip"]) == str(self.ip)

    def default_name(self) -> str:
        tail = self.mac.replace(":", "")[-6:] if self.mac else str(self.ip).rsplit(".", 1)[1]
        return f"device-{tail}"


def _device_list(data: CommentedMap) -> CommentedSeq:
    devices = data.get("devices")
    if devices is None:
        devices = CommentedSeq()
        data["devices"] = devices
    if not isinstance(devices, CommentedSeq):
        raise ConfigEditError("config.yaml: devices must be a list")
    # The template writes `devices: []`; entries read better as a block list.
    devices.fa.set_block_style()
    return devices


def set_device(
    path: Path, ident: DeviceIdent, policy: DevicePolicy, name: str | None, default_name: str
) -> tuple[Config, bool]:
    """Give a device its policy: the existing entry changes, or a new one is added (identified by
    the MAC, or by the address when that is all we have). ``name`` renames; ``default_name`` is
    used only for a new entry without one."""

    def mutate(data: CommentedMap) -> None:
        devices = _device_list(data)
        entry = next((item for item in devices if ident.matches(item)), None)
        if entry is None:
            entry = CommentedMap([("name", name or default_name)])
            if ident.mac is not None:
                entry["mac"] = ident.mac
            else:
                entry["ip"] = str(ident.ip)
            entry["policy"] = policy.value
            devices.append(entry)
            return
        entry["policy"] = policy.value
        if name is not None:
            entry["name"] = name

    return _edit(path, mutate)


def unset_device(path: Path, ident: DeviceIdent) -> tuple[Config, bool]:
    """Remove the device's own policy: it follows routing.mode again."""

    def mutate(data: CommentedMap) -> None:
        devices = _device_list(data)
        for index, item in enumerate(devices):
            if ident.matches(item):
                del devices[index]
                return
        raise DeviceNotFoundError(f"config.yaml has no device {ident.mac or ident.ip}")

    return _edit(path, mutate)
