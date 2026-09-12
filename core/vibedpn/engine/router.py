"""Host networking of the box, rendered from templates and applied through ``nft``.

The only module allowed to change host networking. It never touches the host default route.
Stage 2 ships the VPS firewall (table ``inet vibedpn``, input policy drop); the LAN router
(fwmarks, ``ip rule``, gateway tables) arrives in Stage 4 and extends this module.
"""

from __future__ import annotations

import os
import shutil
import subprocess

from jinja2 import Environment, PackageLoader, StrictUndefined

from vibedpn.config import Config, Role, parse_port_range
from vibedpn.detect import SBIN_DIRS

NFT = "nft"
NFT_TABLE = "inet vibedpn"
WG_INTERFACE = "wg0"
FIREWALL_TEMPLATE = "firewall.nft.j2"
# One transaction that ends without the table whether or not it was loaded: ``delete`` alone
# fails on a missing table, ``add`` of an existing one is a no-op.
FIREWALL_TEARDOWN = f"add table {NFT_TABLE}\ndelete table {NFT_TABLE}\n"


class RouterError(RuntimeError):
    """A user-facing reason why host rules could not be rendered or applied."""


def _environment() -> Environment:
    return Environment(
        loader=PackageLoader("vibedpn", "templates"),
        undefined=StrictUndefined,
        autoescape=False,  # nftables syntax, not HTML
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def firewall_ruleset(config: Config) -> str | None:
    """The nftables ruleset of a VPS, or ``None`` when this box has no host firewall."""
    if config.role is not Role.VPS or not config.firewall.enabled:
        return None
    udp_from = udp_to = None
    if config.provider.enabled:
        udp_from, udp_to = parse_port_range(config.provider.udp_ports)
    return (
        _environment()
        .get_template(FIREWALL_TEMPLATE)
        .render(
            ssh_ports=config.firewall.ssh_ports,
            wg_port=config.wg_server.listen_port if config.wg_server else None,
            provider=config.provider.enabled,
            udp_from=udp_from,
            udp_to=udp_to,
            wg_interface=WG_INTERFACE,
            allow_tcp=config.firewall.allow_tcp,
            allow_udp=config.firewall.allow_udp,
        )
    )


def ssh_rule_present(ruleset: str, ssh_ports: list[int]) -> bool:
    """A guard against a template regression: the rendered text must accept every configured
    ssh port. Whether sshd really listens there is ``doctor``'s check, not this one's."""
    return f"tcp dport {{ {', '.join(str(p) for p in ssh_ports)} }} accept" in ruleset


def find_nft() -> str | None:
    """``nft`` lives in sbin, which a non-root PATH does not include."""
    search = os.pathsep.join([*os.get_exec_path(), *SBIN_DIRS])
    return shutil.which(NFT, path=search)


def _nft(args: list[str], ruleset: str) -> None:
    nft = find_nft()
    if nft is None:
        raise RouterError(
            "nft not found (the core image installs nftables; on a host: apt install nftables)"
        )
    try:
        completed = subprocess.run(
            [nft, *args], input=ruleset, check=False, capture_output=True, text=True
        )
    except OSError as exc:
        raise RouterError(f"cannot run nft: {exc.strerror}") from exc
    if completed.returncode != 0:
        raise RouterError(f"nft {' '.join(args)} failed: {completed.stderr.strip()}")


def check_ruleset(ruleset: str) -> None:
    """Parse-only pass (``nft -c``) so a rendering mistake never reaches the kernel."""
    _nft(["-c", "-f", "-"], ruleset)


def apply_ruleset(ruleset: str) -> None:
    """Load the ruleset atomically; the file replaces the whole table, so it is idempotent."""
    _nft(["-f", "-"], ruleset)


def remove_firewall() -> None:
    """Drop the table if it is loaded, so a disabled or changed configuration is the truth."""
    _nft(["-f", "-"], FIREWALL_TEARDOWN)


def apply_firewall(config: Config) -> bool:
    """Render, check and apply the VPS firewall; ``False`` when this configuration has none
    (a leftover table from an earlier configuration is removed then)."""
    ruleset = firewall_ruleset(config)
    if ruleset is None:
        remove_firewall()
        return False
    if not ssh_rule_present(ruleset, config.firewall.ssh_ports):
        raise RouterError("rendered firewall does not open ssh; refusing to apply it")
    check_ruleset(ruleset)
    apply_ruleset(ruleset)
    return True
