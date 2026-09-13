"""Change routing in ``config.yaml`` in place: exactly the changed line differs, comments stay.

``config.yaml`` is the owner's file: rendering it again from the model would drop their own
comments and ordering. A round-trip load keeps both; the indentation matches the template, so
the diff of ``vibedpn mode full`` is one line. The result is validated with the full model before
it is written, and written atomically — core reads the file at start.
"""

from __future__ import annotations

import io
from pathlib import Path

from pydantic import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from vibedpn.atomic import write_like
from vibedpn.config import Config, RoutingMode, Upstream, parse_yaml

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


def set_routing(
    path: Path, *, mode: RoutingMode | None = None, upstream: Upstream | None = None
) -> tuple[Config, bool]:
    """Set ``routing.mode`` and/or ``routing.default_upstream``; returns the validated result and
    whether the file changed. Nothing is written when the result would not be a valid box."""
    yaml = round_trip_yaml()
    try:
        text = path.read_text(encoding="utf-8")
        data = yaml.load(text)
    except OSError as exc:
        raise ConfigEditError(f"cannot read {path}: {exc.strerror or exc}") from exc
    except YAMLError as exc:
        raise ConfigEditError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("routing"), dict):
        raise ConfigEditError(f"{path} has no routing section: a box of this role routes no LAN")
    if mode is not None:
        data["routing"]["mode"] = mode.value
    if upstream is not None:
        data["routing"]["default_upstream"] = upstream.value
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
