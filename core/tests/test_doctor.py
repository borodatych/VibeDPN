"""Doctor: parsers on real ``ss`` output, verdict table per role, rendering, probes."""

import json
import os
import stat
from ipaddress import IPv4Address
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vibedpn import cli, doctor
from vibedpn.bootstrap import Answers, HostFacts, build_config, render_config
from vibedpn.compose import ServiceStatus
from vibedpn.config import Config, Role
from vibedpn.detect import Interface
from vibedpn.doctor import (
    CheckResult,
    DoctorFacts,
    Listener,
    Verdict,
    evaluate,
    gather,
    has_failures,
    holder_of,
    parse_ss,
    parse_sysctl_flag,
    port_needs,
    render,
    to_json,
)

FIXTURES = Path(__file__).parent / "fixtures"
LAN = HostFacts(Interface("eth0", IPv4Address("192.168.1.50"), 24), wireguard_module=True)


def home_config() -> Config:
    return build_config(Answers(Role.HOME, password="secret123"), LAN)


def vps_config() -> Config:
    return build_config(Answers(Role.VPS, endpoint="vps.example.com"), LAN)


def facts(**overrides: object) -> DoctorFacts:
    base: dict[str, object] = {
        "config": home_config(),
        "config_error": "",
        "config_hint": "",
        "env_current": True,
        "secrets": {"htpasswd": True, "wg-client.conf": False},
        "wireguard": True,
        "nf_tables": True,
        "ip_forward": True,
        "listeners": [],
        "is_root": True,
        "docker_error": "",
        "listeners_error": "",
        "services": [ServiceStatus("core", "running", "healthy", "Up")],
        "active_services": ["core"],
    }
    base.update(overrides)
    return DoctorFacts(**base)  # type: ignore[arg-type]


def by_name(results: list[CheckResult]) -> dict[str, CheckResult]:
    return {item.name: item for item in results}


def test_parse_ss_root_output_has_processes() -> None:
    listeners = parse_ss((FIXTURES / "ss_lntup_root.txt").read_text(encoding="utf-8"))
    assert listeners == [
        Listener("udp", "127.0.0.53", 53, "python3"),
        Listener("tcp", "0.0.0.0", 8080, "python3"),
        Listener("tcp", "*", 3000, "python3"),
    ]


def test_parse_ss_user_output_has_no_processes() -> None:
    listeners = parse_ss((FIXTURES / "ss_lntu_user.txt").read_text(encoding="utf-8"))
    assert [item.process for item in listeners] == ["", "", ""]
    assert parse_ss("udp UNCONN 0 0 127.0.0.53%lo:53 0.0.0.0:*\n")[0].address == "127.0.0.53"
    assert parse_ss("tcp LISTEN 0 0 [::]:80 [::]:*\n")[0].address == "::"
    assert parse_ss("garbage\n") == []


def test_parse_sysctl_flag() -> None:
    assert parse_sysctl_flag("1\n") is True
    assert parse_sysctl_flag("0") is False
    assert parse_sysctl_flag("") is None


def test_port_needs_per_role() -> None:
    home = {(n.service, n.label, n.address) for n in port_needs(home_config())}
    assert ("adguard", "udp/53", "192.168.1.50") in home
    assert ("ui", "tcp/80", "192.168.1.50") in home
    assert ("core", "tcp/4480", "127.0.0.1") in home
    assert ("myst-provider", "tcp/4449", "127.0.0.1") in home
    assert ("myst-provider", "udp/56000-56100", "*") in home
    vps = {(n.service, n.label) for n in port_needs(vps_config())}
    assert ("wg-server", "udp/51820") in vps and ("myst-provider", "tcp/4050") in vps


def test_holder_of_respects_addresses_and_ranges() -> None:
    need = port_needs(home_config())[1]  # adguard udp 53 on the LAN address
    stub = Listener("udp", "127.0.0.53", 53, "systemd-resolve")
    assert holder_of(need, [stub]) is None  # resolved's stub does not collide with LAN:53
    wildcard = Listener("udp", "0.0.0.0", 53, "dnsmasq")
    assert holder_of(need, [wildcard]) == wildcard
    same = Listener("udp", "192.168.1.50", 53, "unbound")
    assert holder_of(need, [same]) == same
    udp_range = next(n for n in port_needs(home_config()) if n.port_end)
    inside = Listener("udp", "0.0.0.0", 56050, "myst")
    assert holder_of(udp_range, [inside]) == inside
    assert holder_of(udp_range, [Listener("udp", "0.0.0.0", 56101, "x")]) is None


def test_all_green() -> None:
    results = evaluate(facts())
    assert not has_failures(results)
    assert by_name(results)["config"].detail.startswith("role home")
    assert by_name(results)["services"].verdict is Verdict.OK


def test_missing_config_carries_its_own_hint() -> None:
    results = evaluate(
        facts(config=None, config_error="no config.yaml", config_hint="run `vibedpn init` first")
    )
    names = by_name(results)
    assert names["config"].verdict is Verdict.FAIL and "init" in names["config"].hint
    assert not any(name.startswith("port") for name in names)


def test_docker_unreachable_makes_ports_uncertain_not_failed() -> None:
    held = [Listener("udp", "192.168.1.50", 53, ""), Listener("tcp", "127.0.0.1", 4480, "")]
    names = by_name(
        evaluate(facts(docker_error="no access to the Docker socket", listeners=held, services=[]))
    )
    assert names["docker"].verdict is Verdict.FAIL
    assert names["port udp/53"].verdict is Verdict.WARN
    assert "until Docker is reachable" in names["port udp/53"].detail
    assert "services" not in names


def test_wireguard_verdict_depends_on_profiles() -> None:
    assert (
        by_name(evaluate(facts(wireguard=False)))["wireguard"].verdict is Verdict.WARN
    )  # home: myst only
    vps = by_name(evaluate(facts(config=vps_config(), wireguard=False)))["wireguard"]
    assert vps.verdict is Verdict.FAIL and "tunnels cannot start" in vps.detail
    unknown = by_name(evaluate(facts(wireguard=None)))["wireguard"]
    assert unknown.verdict is Verdict.WARN and unknown.hint == "sudo vibedpn doctor"


def test_ip_forward_and_nf_tables_verdicts() -> None:
    names = by_name(evaluate(facts(ip_forward=False, nf_tables=False)))
    assert names["ip_forward"].verdict is Verdict.FAIL and "sysctl" in names["ip_forward"].hint
    assert names["nf_tables"].verdict is Verdict.FAIL
    assert by_name(evaluate(facts(ip_forward=None)))["ip_forward"].verdict is Verdict.WARN
    assert by_name(evaluate(facts(nf_tables=None)))["nf_tables"].verdict is Verdict.WARN


def test_port_taken_by_a_stranger_versus_our_container() -> None:
    dnsmasq = Listener("udp", "0.0.0.0", 53, "dnsmasq")
    names = by_name(evaluate(facts(listeners=[dnsmasq])))
    assert names["port udp/53"].verdict is Verdict.FAIL
    assert "dnsmasq" in names["port udp/53"].detail
    ours = facts(
        listeners=[Listener("udp", "192.168.1.50", 53, "AdGuardHome")],
        services=[ServiceStatus("adguard", "running", "healthy", "Up")],
    )
    assert by_name(evaluate(ours))["port udp/53"].detail == "held by our adguard"
    anonymous = facts(listeners=[Listener("udp", "0.0.0.0", 53, "")], is_root=False)
    assert "run with sudo" in by_name(evaluate(anonymous))["port udp/53"].detail


def test_ports_unchecked_without_ss() -> None:
    names = by_name(evaluate(facts(listeners=None, listeners_error="`ss` not found")))
    assert names["port tcp/4480"].verdict is Verdict.WARN
    assert "cannot check" in names["port tcp/4480"].detail


def test_secrets_per_role_and_without_access() -> None:
    names = by_name(evaluate(facts(secrets={"htpasswd": False, "wg-client.conf": False})))
    assert names["secrets"].verdict is Verdict.FAIL
    client = build_config(Answers(Role.CLIENT, password="x" * 8, peer_config=Path("p")), LAN)
    partial = facts(config=client, secrets={"htpasswd": True, "wg-client.conf": False})
    assert by_name(evaluate(partial))["secrets"].detail == "missing wg-client.conf"
    assert (
        by_name(evaluate(facts(config=vps_config())))["secrets"].detail
        == "none needed for this role"
    )
    closed = by_name(evaluate(facts(secrets=None)))["secrets"]
    assert closed.verdict is Verdict.WARN and closed.hint == "sudo vibedpn doctor"
    assert "init" not in closed.hint
    assert (
        by_name(evaluate(facts(config=vps_config(), secrets=None)))["secrets"].verdict is Verdict.OK
    )


def test_services_not_started_broken_or_unhealthy() -> None:
    names = by_name(evaluate(facts(services=[], active_services=["core", "ui"])))
    assert names["services"].verdict is Verdict.WARN and names["services"].hint == "vibedpn up"
    crashed = facts(services=[ServiceStatus("core", "exited", "-", "Exited (1) 5 seconds ago")])
    result = by_name(evaluate(crashed))["services"]
    assert result.verdict is Verdict.FAIL and "Exited (1)" in result.detail
    assert result.hint == "vibedpn logs <service>"
    sick = facts(services=[ServiceStatus("core", "running", "unhealthy", "Up")])
    assert by_name(evaluate(sick))["services"].verdict is Verdict.FAIL


def test_env_verdicts() -> None:
    assert by_name(evaluate(facts(env_current=None)))["env"].verdict is Verdict.WARN
    assert by_name(evaluate(facts(env_current=False)))["env"].detail == ".env is behind config.yaml"


def test_render_and_json() -> None:
    results = evaluate(facts(ip_forward=False))
    text = render(results)
    assert "[FAIL] ip_forward" in text and text.endswith("fail")
    assert "[ ok ] config" in text
    parsed = json.loads(to_json(results))
    assert parsed[0]["name"] == "config" and parsed[0]["verdict"] == "ok"
    assert render([]) == "0 ok, 0 warn, 0 fail"


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_gather_survives_root_only_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    (tmp_path / "config.yaml").write_text(render_config(home_config()), encoding="utf-8")
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "htpasswd").write_text("admin:x\n", encoding="utf-8")
    secrets.chmod(0)
    monkeypatch.setattr(
        doctor, "preflight", lambda: (_ for _ in ()).throw(RuntimeError("no docker"))
    )
    monkeypatch.setattr(doctor, "module_present", lambda _name: None)
    monkeypatch.setattr(doctor, "_listeners", lambda: (None, "`ss` not found"))
    try:
        with pytest.raises(RuntimeError):  # preflight fake proves gather reached docker probing
            gather(tmp_path)
    finally:
        secrets.chmod(stat.S_IRWXU)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_secrets_probe_returns_none_when_closed(tmp_path: Path) -> None:
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    secrets.chmod(0)
    try:
        assert doctor._secrets(tmp_path) is None
    finally:
        secrets.chmod(stat.S_IRWXU)
    assert doctor._secrets(tmp_path) == {"htpasswd": False, "wg-client.conf": False}


def test_doctor_command_exit_codes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr(cli, "gather", lambda _box: facts())
    result = runner.invoke(cli.app, ["doctor", "--dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "0 fail" in result.output
    monkeypatch.setattr(
        cli, "gather", lambda _box: facts(docker_error="docker not found; run install.sh")
    )
    result = runner.invoke(cli.app, ["doctor", "--dir", str(tmp_path), "--json"])
    assert result.exit_code == 1
    verdicts = {item["name"]: item["verdict"] for item in json.loads(result.output)}
    assert verdicts["docker"] == "fail"
