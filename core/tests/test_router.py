"""VPS firewall: rendering, the lock-out guard, nft invocation and core start-up."""

import os
import subprocess
from ipaddress import IPv4Address
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from vibedpn.api import server
from vibedpn.bootstrap import Answers, HostFacts, build_config
from vibedpn.config import Config, FirewallConfig, Role
from vibedpn.detect import Interface
from vibedpn.engine import router
from vibedpn.engine.router import (
    Egress,
    RouterError,
    apply_firewall,
    apply_tunnel_egress,
    docker_user_rules,
    egress_ruleset,
    firewall_ruleset,
    plan_docker_user,
    ssh_rule_present,
)
from vibedpn.engine.wg import ServerFiles, add_peer, ensure_server

FACTS = HostFacts(None, wireguard_module=True, ssh_ports=[22, 2222])
NFT_PATH = "/usr/sbin/nft"


def vps(**firewall: object) -> Config:
    config = build_config(Answers(Role.VPS, endpoint="vps.example.com"), FACTS)
    if firewall:
        return config.model_copy(update={"firewall": FirewallConfig(**firewall)})  # type: ignore[arg-type]
    return config


def test_ruleset_opens_exactly_what_the_role_needs() -> None:
    text = firewall_ruleset(vps())
    assert text is not None
    assert "policy drop" in text
    assert "tcp dport { 22, 2222 } accept" in text
    assert "udp dport 51820 accept" in text
    assert "elements = { 56000-56100 }" in text and "udp dport @myst_udp accept" in text
    assert (
        'ip daddr 10.78.0.0/24 iifname != "wg0" drop'
        ' comment "the tunnel subnet only through the tunnel"'
    ) in text
    assert 'iifname "wg0" tcp dport { 4449, 4480 } accept' in text
    assert 'iifname "wg0" accept' not in text  # a home box sees the panel and the API, not ssh
    assert "owner" not in text
    assert (
        text.startswith("# VibeDPN host firewall")
        and "add table inet vibedpn\ndelete table inet vibedpn" in text
    )


def test_ruleset_adds_owner_ports_and_drops_node_set_without_provider() -> None:
    text = firewall_ruleset(vps(allow_tcp=[443], allow_udp=[5000, 5001]))
    assert text is not None
    assert 'tcp dport { 443 } accept comment "owner"' in text
    assert 'udp dport { 5000, 5001 } accept comment "owner"' in text
    quiet = vps().model_copy(
        update={"provider": vps().provider.model_copy(update={"enabled": False})}
    )
    text = firewall_ruleset(quiet)
    assert text is not None and "myst_udp" not in text


def test_no_ruleset_for_lan_roles_or_disabled_firewall() -> None:
    lan = HostFacts(Interface("eth0", IPv4Address("192.168.1.50"), 24), wireguard_module=True)
    home = build_config(Answers(Role.HOME, password="secret123"), lan)
    assert firewall_ruleset(home) is None
    assert firewall_ruleset(vps(enabled=False)) is None


def test_ssh_guard() -> None:
    text = firewall_ruleset(vps())
    assert text is not None
    assert ssh_rule_present(text, [22, 2222])
    assert not ssh_rule_present(text.replace("22, 2222", "23"), [22, 2222])


def test_apply_firewall_checks_then_applies(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], str]] = []

    def fake_run(argv: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((argv[1:], str(kwargs["input"])))
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(router, "find_nft", lambda: "/usr/sbin/nft")
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert apply_firewall(vps()) is True
    assert [argv for argv, _ in calls] == [["-c", "-f", "-"], ["-f", "-"]]
    assert all("tcp dport { 22, 2222 } accept" in text for _, text in calls)


def test_apply_firewall_removes_the_table_when_config_has_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``enabled: false`` or a LAN role after a vps life: the leftover policy drop must go."""
    calls: list[tuple[list[str], str]] = []

    def fake_run(argv: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((argv[1:], str(kwargs["input"])))
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(router, "find_nft", lambda: "/usr/sbin/nft")
    monkeypatch.setattr(subprocess, "run", fake_run)
    lan = HostFacts(Interface("eth0", IPv4Address("192.168.1.50"), 24), wireguard_module=True)
    home = build_config(Answers(Role.HOME, password="secret123"), lan)
    assert apply_firewall(vps(enabled=False)) is False
    assert apply_firewall(home) is False
    teardown = "add table inet vibedpn\ndelete table inet vibedpn\n"
    assert calls == [(["-f", "-"], teardown), (["-f", "-"], teardown)]


def test_ruleset_replaces_the_whole_table() -> None:
    """``flush table`` keeps set elements: a narrowed UDP range would clash (EEXIST) or pile up."""
    text = firewall_ruleset(vps())
    assert text is not None
    assert text.index("add table inet vibedpn\n") < text.index("delete table inet vibedpn\n")
    assert not any(line.startswith("flush") for line in text.splitlines())


def test_ruleset_lets_dhcpv6_replies_in() -> None:
    """A DHCPv6 reply is not "established" for conntrack (multicast solicit, link-local reply)."""
    text = firewall_ruleset(vps())
    assert text is not None
    assert (
        "ip6 saddr fe80::/10 ip6 daddr fe80::/10 udp sport 547 udp dport 546 accept"
        ' comment "dhcpv6 client"'
    ) in text


def test_apply_firewall_reports_nft_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(router, "find_nft", lambda: None)
    with pytest.raises(RouterError, match="nft not found"):
        apply_firewall(vps())

    def failing(argv: list[str], **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=1, stderr="Error: syntax error, line 3")

    monkeypatch.setattr(router, "find_nft", lambda: "/usr/sbin/nft")
    monkeypatch.setattr(subprocess, "run", failing)
    with pytest.raises(RouterError, match="syntax error"):
        apply_firewall(vps())


def test_core_reports_a_configuration_without_firewall(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        "version: 1\nrole: vps\nprovider: {enabled: true}\n"
        "wg_server: {endpoint: 203.0.113.7}\nfirewall: {enabled: false}\n",
        encoding="utf-8",
    )
    with (
        patch.dict(
            "os.environ",
            {
                server.CONFIG_PATH_ENV: str(config),
                server.SECRETS_DIR_ENV: str(tmp_path / "secrets"),
            },
        ),
        patch("vibedpn.api.server.apply_firewall", return_value=False),
        patch("vibedpn.api.server.apply_tunnel_egress", return_value=Egress.NO_DOCKER_DROP),
        patch("vibedpn.api.server.run_servers"),
    ):
        server.main()
    assert "table inet vibedpn removed if it was loaded" in capsys.readouterr().err


def test_core_applies_the_firewall_before_serving(tmp_path: Path) -> None:
    good = tmp_path / "config.yaml"
    good.write_text(
        "version: 1\nrole: vps\nprovider: {enabled: true}\nwg_server: {endpoint: 203.0.113.7}\n",
        encoding="utf-8",
    )
    with (
        patch.dict(
            "os.environ",
            {server.CONFIG_PATH_ENV: str(good), server.SECRETS_DIR_ENV: str(tmp_path / "secrets")},
        ),
        patch("vibedpn.api.server.apply_firewall", return_value=True) as applied,
        patch("vibedpn.api.server.apply_tunnel_egress", return_value=Egress.DOCKER_USER) as egress,
        patch("vibedpn.api.server.run_servers") as run,
    ):
        server.main()
    applied.assert_called_once()
    egress.assert_called_once()
    run.assert_called_once()
    with (
        patch.dict(
            "os.environ",
            {server.CONFIG_PATH_ENV: str(good), server.SECRETS_DIR_ENV: str(tmp_path / "secrets")},
        ),
        patch("vibedpn.api.server.apply_firewall", side_effect=RouterError("nft failed")),
        patch("vibedpn.api.server.run_servers") as run,
        pytest.raises(SystemExit) as excinfo,
    ):
        server.main()
    assert excinfo.value.code == 78
    run.assert_not_called()


VPS_CONFIG = (
    "version: 1\nrole: vps\nprovider: {enabled: true}\nwg_server: {endpoint: 203.0.113.7}\n"
)


def test_core_renders_the_tunnel_after_the_firewall_and_before_serving(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(VPS_CONFIG, encoding="utf-8")
    secrets = tmp_path / "secrets"
    order: list[str] = []

    def tunnel(loaded: Config, secrets_dir: Path) -> ServerFiles | None:
        order.append("tunnel")
        return ensure_server(loaded, secrets_dir)

    def serve(*_args: object, **_kwargs: object) -> None:
        # The API must never come up before wg0.conf is on disk: compose starts wg-server
        # as soon as core reports healthy.
        assert (secrets / "wg-server" / "wg0.conf").is_file()
        order.append("api")

    def egress(_config: Config) -> Egress:
        order.append("egress")
        return Egress.DOCKER_USER

    with (
        patch.dict(
            "os.environ",
            {server.CONFIG_PATH_ENV: str(config), server.SECRETS_DIR_ENV: str(secrets)},
        ),
        patch("vibedpn.api.server.apply_firewall", side_effect=lambda _c: order.append("firewall")),
        patch("vibedpn.api.server.apply_tunnel_egress", side_effect=egress),
        patch("vibedpn.api.server.ensure_server", side_effect=tunnel),
        patch("vibedpn.api.server.run_servers", side_effect=serve),
    ):
        server.main()
    assert order == ["firewall", "egress", "tunnel", "api"]
    assert "ListenPort = 51820" in (secrets / "wg-server" / "wg0.conf").read_text(encoding="utf-8")


def test_core_refuses_to_start_on_a_broken_tunnel_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(VPS_CONFIG, encoding="utf-8")
    directory = tmp_path / "secrets" / "wg-server"
    directory.mkdir(parents=True)
    (directory / "server.key").write_text("garbage\n", encoding="utf-8")
    with (
        patch.dict(
            "os.environ",
            {
                server.CONFIG_PATH_ENV: str(config),
                server.SECRETS_DIR_ENV: str(tmp_path / "secrets"),
            },
        ),
        patch("vibedpn.api.server.apply_firewall", return_value=True),
        patch("vibedpn.api.server.apply_tunnel_egress", return_value=Egress.DOCKER_USER),
        patch("vibedpn.api.server.run_servers") as run,
        pytest.raises(SystemExit) as exit_info,
    ):
        server.main()
    assert exit_info.value.code == os.EX_CONFIG
    assert "restore it from a backup" in capsys.readouterr().err
    run.assert_not_called()


def test_core_reports_peers_moved_by_a_subnet_change(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    secrets = tmp_path / "secrets"
    old = Config.model_validate(
        {
            "version": 1,
            "role": "vps",
            "provider": {"enabled": True},
            "wg_server": {"endpoint": "203.0.113.7"},
        }
    )
    add_peer(old, secrets, "dacha")
    config = tmp_path / "config.yaml"
    config.write_text(
        VPS_CONFIG.replace(
            "{endpoint: 203.0.113.7}", "{endpoint: 203.0.113.7, subnet: 10.99.0.0/24}"
        ),
        encoding="utf-8",
    )
    with (
        patch.dict(
            "os.environ",
            {server.CONFIG_PATH_ENV: str(config), server.SECRETS_DIR_ENV: str(secrets)},
        ),
        patch("vibedpn.api.server.apply_firewall", return_value=True),
        patch("vibedpn.api.server.apply_tunnel_egress", return_value=Egress.DOCKER_USER),
        patch("vibedpn.api.server.run_servers"),
    ):
        server.main()
    assert (
        "peer dacha moved from 10.78.0.2 to 10.99.0.2; run `vibedpn peer export dacha`"
        in capsys.readouterr().err
    )


def test_tunnel_input_follows_the_api_port_and_subnet() -> None:
    raw = {
        "version": 1,
        "role": "vps",
        "provider": {"enabled": True},
        "wg_server": {"endpoint": "203.0.113.7", "subnet": "10.99.0.0/16"},
        "api": {"port": 4499},
    }
    text = firewall_ruleset(Config.model_validate(raw))
    assert text is not None
    assert 'ip daddr 10.99.0.0/16 iifname != "wg0" drop' in text
    assert 'iifname "wg0" tcp dport { 4449, 4499 } accept' in text
    # The anti-spoofing drop comes before anything that could accept the packet.
    assert text.index('iifname != "wg0" drop') < text.index("tcp dport { 22")


def test_egress_nats_the_tunnel_subnet_whatever_the_firewall() -> None:
    for config in (vps(), vps(enabled=False)):
        text = egress_ruleset(config)
        assert text is not None
        assert "add table inet vibedpn_egress\ndelete table inet vibedpn_egress" in text
        assert 'ip saddr 10.78.0.0/24 oifname != "wg0" masquerade' in text
        assert 'ip saddr 10.78.0.0/24 iifname != "wg0" drop' in text
        assert (
            'ip daddr 10.78.0.0/24 oifname "wg0" ct state != { established, related } drop' in text
        )
        # Other forwarding of the host is not ours to judge.
        assert "; policy drop;" not in text
        assert text.count("; policy accept;") == 2


def test_no_egress_without_a_tunnel() -> None:
    lan = HostFacts(Interface("eth0", IPv4Address("192.168.1.50"), 24), wireguard_module=True)
    home = build_config(Answers(Role.HOME, password="secret123"), lan)
    assert egress_ruleset(home) is None
    assert docker_user_rules(home) == []


# The exact listing `iptables-nft -S DOCKER-USER` printed on Docker 29.5.2 (colima VM,
# 2026-09-13), with the warning line the nft backend adds when legacy tables exist.
LISTING = """# Warning: iptables-legacy tables present, use iptables-legacy to see them
-N DOCKER-USER
-A DOCKER-USER -d 10.78.0.0/24 ! -i wg0 -o wg0 -m conntrack --ctstate RELATED,ESTABLISHED -m comment --comment vibedpn-egress -j ACCEPT
-A DOCKER-USER -s 10.78.0.0/24 -i wg0 ! -o wg0 -m comment --comment vibedpn-egress -j ACCEPT
"""  # noqa: E501


def test_docker_user_plan_is_empty_when_the_rules_are_in_place() -> None:
    assert plan_docker_user(LISTING, docker_user_rules(vps())) == ([], [])


def test_docker_user_plan_replaces_an_old_subnet_and_keeps_foreign_rules() -> None:
    raw = {
        "version": 1,
        "role": "vps",
        "provider": {"enabled": True},
        "wg_server": {"endpoint": "203.0.113.7", "subnet": "10.99.0.0/24"},
    }
    moved = Config.model_validate(raw)
    listing = LISTING + "-A DOCKER-USER -i eth1 -j DROP\n"
    delete, insert = plan_docker_user(listing, docker_user_rules(moved))
    assert len(delete) == 2 and all("10.78.0.0/24" in rule for rule in delete)
    assert insert == docker_user_rules(moved)
    assert not any("eth1" in rule for rule in delete)


def test_docker_user_plan_drops_duplicates_and_everything_without_a_tunnel() -> None:
    doubled = LISTING + LISTING.splitlines()[-1] + "\n"
    delete, insert = plan_docker_user(doubled, docker_user_rules(vps()))
    assert len(delete) == 3 and insert == docker_user_rules(vps())
    delete, insert = plan_docker_user(LISTING, [])
    assert len(delete) == 2 and insert == []


def test_docker_user_rules_below_a_foreign_drop_are_reinserted_on_top() -> None:
    """An owner's DROP (or Docker's RETURN) above our accepts makes them dead."""
    lines = LISTING.splitlines()
    shadowed = "\n".join([*lines[:2], "-A DOCKER-USER -j RETURN", *lines[2:]]) + "\n"
    delete, insert = plan_docker_user(shadowed, docker_user_rules(vps()))
    assert len(delete) == 2 and insert == docker_user_rules(vps())


def test_egress_keeps_peers_off_containers_and_private_networks() -> None:
    text = egress_ruleset(vps())
    assert text is not None
    assert 'ip saddr 10.78.0.0/24 oifname "docker0" drop' in text
    assert 'ip saddr 10.78.0.0/24 oifname "br-*" drop' in text
    assert "169.254.0.0/16, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 100.64.0.0/10" in text


def test_egress_clamps_mss_both_ways() -> None:
    text = egress_ruleset(vps())
    assert text is not None
    assert 'iifname "wg0" tcp flags syn tcp option maxseg size set rt mtu' in text
    assert 'oifname "wg0" tcp flags syn tcp option maxseg size set rt mtu' in text


def fake_iptables(
    monkeypatch: pytest.MonkeyPatch, listings: dict[str, SimpleNamespace]
) -> list[list[str]]:
    """nft always succeeds; iptables answers ``-S`` from ``listings`` by binary name."""
    calls: list[list[str]] = []

    def run(argv: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(argv)
        if argv[0] == NFT_PATH:  # not endswith: "iptables-nft" ends with "nft" too
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if "-S" in argv:
            return listings[argv[0]]
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(router, "find_nft", lambda: NFT_PATH)
    monkeypatch.setattr(router, "find_iptables", lambda: list(listings))
    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_apply_egress_opens_docker_user_once(monkeypatch: pytest.MonkeyPatch) -> None:
    empty = SimpleNamespace(returncode=0, stdout="-N DOCKER-USER\n", stderr="")
    calls = fake_iptables(monkeypatch, {"iptables-nft": empty})
    assert apply_tunnel_egress(vps()) is Egress.DOCKER_USER
    inserts = [argv for argv in calls if "-I" in argv]
    assert len(inserts) == 2
    assert all(argv[1:5] == ["-w", "-I", "DOCKER-USER", "1"] for argv in inserts)
    assert [argv[1:] for argv in calls if argv[0] == NFT_PATH] == [
        ["-c", "-f", "-"],
        ["-f", "-"],
    ]
    calls = fake_iptables(
        monkeypatch, {"iptables-nft": SimpleNamespace(returncode=0, stdout=LISTING, stderr="")}
    )
    assert apply_tunnel_egress(vps()) is Egress.DOCKER_USER
    assert not [argv for argv in calls if "-I" in argv or "-D" in argv]


def test_apply_egress_without_docker_drop_and_on_a_legacy_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    no_chain = SimpleNamespace(
        returncode=1, stdout="", stderr="iptables: No chain/target/match by that name."
    )
    legacy_broken = SimpleNamespace(
        returncode=3, stdout="", stderr="can't initialize iptables table"
    )
    fake_iptables(monkeypatch, {"iptables-nft": no_chain, "iptables-legacy": legacy_broken})
    assert apply_tunnel_egress(vps()) is Egress.NO_DOCKER_DROP
    legacy = SimpleNamespace(returncode=0, stdout="-N DOCKER-USER\n", stderr="")
    calls = fake_iptables(monkeypatch, {"iptables-nft": no_chain, "iptables-legacy": legacy})
    assert apply_tunnel_egress(vps()) is Egress.DOCKER_USER
    assert all(argv[0] == "iptables-legacy" for argv in calls if "-I" in argv)


def test_apply_egress_refuses_an_unknown_iptables_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    denied = SimpleNamespace(returncode=4, stdout="", stderr="Permission denied (you must be root)")
    fake_iptables(monkeypatch, {"iptables-nft": denied})
    with pytest.raises(RouterError, match="Permission denied"):
        apply_tunnel_egress(vps())
    fake_iptables(monkeypatch, {})
    with pytest.raises(RouterError, match="iptables not found"):
        apply_tunnel_egress(vps())


def test_egress_is_removed_with_the_tunnel(monkeypatch: pytest.MonkeyPatch) -> None:
    lan = HostFacts(Interface("eth0", IPv4Address("192.168.1.50"), 24), wireguard_module=True)
    home = build_config(Answers(Role.HOME, password="secret123"), lan)
    calls = fake_iptables(
        monkeypatch, {"iptables-nft": SimpleNamespace(returncode=0, stdout=LISTING, stderr="")}
    )
    assert apply_tunnel_egress(home) is Egress.NONE
    assert len([argv for argv in calls if "-D" in argv]) == 2
    fake_iptables(monkeypatch, {})  # no iptables at all: the table still goes, nothing raises
    assert apply_tunnel_egress(home) is Egress.NONE
