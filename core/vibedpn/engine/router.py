"""Host networking of the box, rendered from templates and applied through ``nft``.

The only module allowed to change host networking. It never touches the host default route.
Stage 2 ships the VPS firewall (table ``inet vibedpn``, input policy drop); Stage 3 lets tunnel
peers out through the VPS (table ``inet vibedpn_egress`` plus the ``DOCKER-USER`` rules that open
Docker's forward drop); the LAN router (fwmarks, ``ip rule``, gateway tables) arrives in Stage 4
and extends this module.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from enum import StrEnum

from vibedpn.config import Config, Role, parse_port_range
from vibedpn.detect import SBIN_DIRS
from vibedpn.engine.myst import NODEUI_PORT
from vibedpn.templating import template_environment

NFT = "nft"
NFT_TABLE = "inet vibedpn"
WG_INTERFACE = "wg0"
FIREWALL_TEMPLATE = "firewall.nft.j2"
# One transaction that ends without the table whether or not it was loaded: ``delete`` alone
# fails on a missing table, ``add`` of an existing one is a no-op.
FIREWALL_TEARDOWN = f"add table {NFT_TABLE}\ndelete table {NFT_TABLE}\n"
EGRESS_TABLE = "inet vibedpn_egress"
EGRESS_TEMPLATE = "tunnel-egress.nft.j2"
EGRESS_TEARDOWN = f"add table {EGRESS_TABLE}\ndelete table {EGRESS_TABLE}\n"
# Docker sets the iptables FORWARD policy to drop, and an accept in our own nft table cannot
# override a drop in another one; DOCKER-USER is the chain Docker leaves to the host owner.
DOCKER_USER = "DOCKER-USER"
EGRESS_COMMENT = "vibedpn-egress"  # marks our rules among the owner's in DOCKER-USER
IPTABLES_BACKENDS = ("iptables-nft", "iptables-legacy")
NO_CHAIN = "No chain/target/match by that name"
# Peers get the internet, not the VPS's neighbourhood: link-local (cloud metadata), RFC 1918
# (VPC, Docker networks) and CGNAT. Traffic to the tunnel itself never matches (oifname wg0).
EGRESS_BLOCKED_RANGES = (
    "169.254.0.0/16",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "100.64.0.0/10",
)


class RouterError(RuntimeError):
    """A user-facing reason why host rules could not be rendered or applied."""


def firewall_ruleset(config: Config) -> str | None:
    """The nftables ruleset of a VPS, or ``None`` when this box has no host firewall."""
    if config.role is not Role.VPS or not config.firewall.enabled:
        return None
    udp_from = udp_to = None
    if config.provider.enabled:
        udp_from, udp_to = parse_port_range(config.provider.udp_ports)
    return (
        template_environment()
        .get_template(FIREWALL_TEMPLATE)
        .render(
            ssh_ports=config.firewall.ssh_ports,
            wg_port=config.wg_server.listen_port if config.wg_server else None,
            provider=config.provider.enabled,
            udp_from=udp_from,
            udp_to=udp_to,
            wg_interface=WG_INTERFACE,
            tunnel_subnet=str(config.wg_server.subnet) if config.wg_server else None,
            tunnel_tcp_ports=[NODEUI_PORT, config.api.port],
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


class Egress(StrEnum):
    """What ``apply_tunnel_egress`` left on the host."""

    NONE = "none"  # no tunnel in this configuration; leftovers removed
    DOCKER_USER = "docker-user"  # table loaded, Docker's forward drop opened in DOCKER-USER
    NO_DOCKER_DROP = "no-docker-drop"  # table loaded, no DOCKER-USER chain to open


def egress_ruleset(config: Config) -> str | None:
    """Forward and NAT of the tunnel subnet on a VPS, or ``None`` when there is no tunnel."""
    if config.role is not Role.VPS or config.wg_server is None:
        return None
    return (
        template_environment()
        .get_template(EGRESS_TEMPLATE)
        .render(
            wg_interface=WG_INTERFACE,
            tunnel_subnet=str(config.wg_server.subnet),
            private_ranges=EGRESS_BLOCKED_RANGES,
        )
    )


def docker_user_rules(config: Config) -> list[list[str]]:
    """``DOCKER-USER`` rules in the exact form ``iptables -S`` prints them back, so a listing
    compares equal to what is wanted. Empty when this configuration has no tunnel."""
    if config.role is not Role.VPS or config.wg_server is None:
        return []
    subnet = str(config.wg_server.subnet)
    comment = ["-m", "comment", "--comment", EGRESS_COMMENT]
    return [
        ["-s", subnet, "-i", WG_INTERFACE, "!", "-o", WG_INTERFACE, *comment, "-j", "ACCEPT"],
        [
            "-d", subnet, "!", "-i", WG_INTERFACE, "-o", WG_INTERFACE,
            "-m", "conntrack", "--ctstate", "RELATED,ESTABLISHED", *comment, "-j", "ACCEPT",
        ],
    ]  # fmt: skip


def plan_docker_user(
    listing: str, wanted: list[list[str]]
) -> tuple[list[list[str]], list[list[str]]]:
    """``(delete, insert)`` that turns our rules in ``iptables -S DOCKER-USER`` into ``wanted``:
    rules of an old subnet and duplicates go, missing ones come; foreign rules are untouched.
    Ours count only as the first rules of the chain: an owner's DROP or Docker's RETURN above
    them would make them dead, so then all of ours are reinserted at the top."""
    rules = [
        args[2:]
        for line in listing.splitlines()
        if (args := shlex.split(line))[:2] == ["-A", DOCKER_USER]
    ]
    ours = [rule for rule in rules if EGRESS_COMMENT in rule]
    if wanted and sorted(rules[: len(wanted)]) == sorted(wanted) and len(ours) == len(wanted):
        return [], []
    return ours, list(wanted)


def find_iptables() -> list[str]:
    """Installed iptables backends, nft first; they live in sbin like ``nft``."""
    search = os.pathsep.join([*os.get_exec_path(), *SBIN_DIRS])
    return [path for name in IPTABLES_BACKENDS if (path := shutil.which(name, path=search))]


def docker_user_chain() -> tuple[str, str] | None:
    """``(iptables binary, listing)`` of the backend whose filter table has ``DOCKER-USER``, or
    ``None`` when neither backend has the chain (Docker with its nftables backend, or no Docker).
    Raises when no iptables is installed or the listing fails for another reason."""
    binaries = find_iptables()
    if not binaries:
        raise RouterError(
            "iptables not found (the core image installs it; on a host: apt install iptables)"
        )
    for binary in binaries:
        try:
            listing = subprocess.run(
                [binary, "-w", "-S", DOCKER_USER], check=False, capture_output=True, text=True
            )
        except OSError as exc:
            raise RouterError(f"cannot run {binary}: {exc.strerror}") from exc
        if listing.returncode == 0:
            return binary, listing.stdout
        # The legacy backend fails in its own ways on an nft host (no ip_tables module): only the
        # backend Docker actually uses can have the chain, so any legacy failure means "not here".
        if NO_CHAIN not in listing.stderr and not binary.endswith("legacy"):
            raise RouterError(f"{binary} -S {DOCKER_USER} failed: {listing.stderr.strip()}")
    return None


def sync_docker_user(wanted: list[list[str]]) -> bool:
    """Make our ``DOCKER-USER`` rules exactly ``wanted``; ``False`` when there is no such chain."""
    found = docker_user_chain()
    if found is None:
        return False
    binary, listing = found
    delete, insert = plan_docker_user(listing, wanted)
    commands = [["-D", DOCKER_USER, *rule] for rule in delete]
    # Inserted at the top: Docker may end the chain with RETURN on older versions.
    commands += [["-I", DOCKER_USER, "1", *rule] for rule in reversed(insert)]
    for command in commands:
        completed = subprocess.run(
            [binary, "-w", *command], check=False, capture_output=True, text=True
        )
        if completed.returncode != 0:
            raise RouterError(
                f"{binary} {' '.join(command[:2])} failed: {completed.stderr.strip()}"
            )
    return True


def apply_tunnel_egress(config: Config) -> Egress:
    """Let tunnel peers out to the internet: NAT and forward table, then ``DOCKER-USER``.
    Without a tunnel both are removed, so a VPS that stopped serving peers forwards nothing."""
    ruleset = egress_ruleset(config)
    if ruleset is None:
        # DOCKER-USER first: a failing nft must not leave the forward drop opened.
        if find_iptables():  # without iptables nothing of ours can be in DOCKER-USER either
            sync_docker_user([])
        _nft(["-f", "-"], EGRESS_TEARDOWN)
        return Egress.NONE
    check_ruleset(ruleset)
    apply_ruleset(ruleset)
    if sync_docker_user(docker_user_rules(config)):
        return Egress.DOCKER_USER
    return Egress.NO_DOCKER_DROP


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
