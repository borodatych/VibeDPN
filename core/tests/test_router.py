"""VPS firewall: rendering, the lock-out guard, nft invocation and core start-up."""

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
    RouterError,
    apply_firewall,
    firewall_ruleset,
    ssh_rule_present,
)

FACTS = HostFacts(None, wireguard_module=True, ssh_ports=[22, 2222])


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
    assert 'iifname "wg0" accept' in text
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
        patch.dict("os.environ", {server.CONFIG_PATH_ENV: str(config)}),
        patch("vibedpn.api.server.apply_firewall", return_value=False),
        patch("vibedpn.api.server.uvicorn.run"),
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
        patch.dict("os.environ", {server.CONFIG_PATH_ENV: str(good)}),
        patch("vibedpn.api.server.apply_firewall", return_value=True) as applied,
        patch("vibedpn.api.server.uvicorn.run") as run,
    ):
        server.main()
    applied.assert_called_once()
    run.assert_called_once()
    with (
        patch.dict("os.environ", {server.CONFIG_PATH_ENV: str(good)}),
        patch("vibedpn.api.server.apply_firewall", side_effect=RouterError("nft failed")),
        patch("vibedpn.api.server.uvicorn.run") as run,
        pytest.raises(SystemExit) as excinfo,
    ):
        server.main()
    assert excinfo.value.code == 78
    run.assert_not_called()
