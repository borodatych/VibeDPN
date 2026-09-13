"""Doctor: parsers on real ``ss`` output, verdict table per role, rendering, probes."""

import json
import os
import stat
import urllib.request
from ipaddress import IPv4Address
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vibedpn import cli, doctor
from vibedpn.bootstrap import Answers, HostFacts, build_config, render_config, secrets_present
from vibedpn.compose import ServiceStatus
from vibedpn.config import Config, DeviceConfig, DevicePolicy, FirewallConfig, Role, parse_yaml
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
        "secrets": {"htpasswd": True, "wg-client.conf": False, "nodeui-pass": True},
        "wireguard": True,
        "nf_tables": True,
        "ip_forward": True,
        "listeners": [],
        "is_root": True,
        "docker_error": "",
        "listeners_error": "",
        "services": [ServiceStatus("core", "running", "healthy", "Up")],
        "active_services": ["core"],
        "firewall_table": None,
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
    vps = by_name(
        evaluate(facts(config=vps_config(), secrets={"htpasswd": True, "nodeui-pass": False}))
    )["secrets"]
    assert vps.verdict is Verdict.FAIL and vps.detail == "missing nodeui-pass"
    closed = by_name(evaluate(facts(secrets={"htpasswd": None, "nodeui-pass": True})))["secrets"]
    assert closed.verdict is Verdict.WARN and closed.hint == "sudo vibedpn doctor"
    assert "cannot check htpasswd" in closed.detail and "init" not in closed.hint


def test_services_not_started_broken_or_unhealthy() -> None:
    names = by_name(evaluate(facts(services=[], active_services=["core", "ui"])))
    assert names["services"].verdict is Verdict.WARN and names["services"].hint == "vibedpn up"
    crashed = facts(services=[ServiceStatus("core", "exited", "-", "Exited (1) 5 seconds ago")])
    result = by_name(evaluate(crashed))["services"]
    assert result.verdict is Verdict.FAIL and "Exited (1)" in result.detail
    assert result.hint == "vibedpn logs <service>"
    sick = facts(services=[ServiceStatus("core", "running", "unhealthy", "Up")])
    assert by_name(evaluate(sick))["services"].verdict is Verdict.FAIL


def test_firewall_verdicts_only_for_vps() -> None:
    assert "firewall" not in by_name(evaluate(facts(firewall_table=False)))
    loaded = by_name(
        evaluate(
            facts(
                config=vps_config(),
                secrets={"htpasswd": True, "nodeui-pass": True},
                firewall_table=True,
            )
        )
    )["firewall"]
    assert loaded.verdict is Verdict.OK
    missing = by_name(evaluate(facts(config=vps_config(), firewall_table=False)))["firewall"]
    assert missing.verdict is Verdict.FAIL and "vibedpn up" in missing.hint
    unknown = by_name(
        evaluate(
            facts(
                config=vps_config(),
                firewall_table=None,
                firewall_error="nft cannot list tables: not root",
                is_root=False,
            )
        )
    )["firewall"]
    assert unknown.verdict is Verdict.WARN and unknown.hint == "sudo vibedpn doctor"
    no_nft = by_name(
        evaluate(
            facts(
                config=vps_config(),
                firewall_table=None,
                firewall_error="nft not found on the host (apt install nftables)",
            )
        )
    )["firewall"]
    assert no_nft.verdict is Verdict.WARN
    assert "apt install nftables" in no_nft.detail and no_nft.hint == ""


def disabled_vps() -> Config:
    return vps_config().model_copy(update={"firewall": FirewallConfig(enabled=False)})


def test_disabled_firewall_must_not_stay_loaded() -> None:
    stale = by_name(evaluate(facts(config=disabled_vps(), firewall_table=True)))["firewall"]
    assert stale.verdict is Verdict.WARN and "vibedpn restart" in stale.hint
    clean = by_name(evaluate(facts(config=disabled_vps(), firewall_table=False)))["firewall"]
    assert clean.verdict is Verdict.OK
    assert "firewall" not in by_name(evaluate(facts(config=disabled_vps(), firewall_table=None)))


def test_sshd_ports_must_be_open_in_the_firewall() -> None:
    sshd = [Listener("tcp", "0.0.0.0", 22, "sshd"), Listener("tcp", "0.0.0.0", 2222, "sshd")]
    names = by_name(evaluate(facts(config=vps_config(), firewall_table=True, listeners=sshd)))
    assert names["ssh"].verdict is Verdict.FAIL
    assert names["ssh"].detail == "sshd listens on 2222, which firewall.ssh_ports does not open"
    assert "firewall.ssh_ports" in names["ssh"].hint
    fine = facts(config=vps_config(), firewall_table=True, listeners=sshd[:1])
    assert by_name(evaluate(fine))["ssh"].verdict is Verdict.OK
    # No sshd visible (not root, or socket-activated): nothing to compare against.
    anonymous = facts(config=vps_config(), firewall_table=True, listeners=[])
    assert "ssh" not in by_name(evaluate(anonymous))
    unknown = facts(config=vps_config(), firewall_table=True, listeners=None)
    assert "ssh" not in by_name(evaluate(unknown))


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
def test_secrets_probe_is_per_file(tmp_path: Path) -> None:
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    node = tmp_path / "data" / "myst-provider"
    node.mkdir(parents=True)
    (node / "nodeui-pass").write_text("$2b$x\n", encoding="utf-8")
    secrets.chmod(0)
    try:
        assert secrets_present(tmp_path) == {
            "htpasswd": None,
            "wg-client.conf": None,
            "ui-db-password": None,
            "ui-auth-secret": None,
            "adguard-core-password": None,
            "myst-consumer-passphrase": None,
            "nodeui-pass": True,
        }
    finally:
        secrets.chmod(stat.S_IRWXU)
    assert secrets_present(tmp_path) == {
        "htpasswd": False,
        "wg-client.conf": False,
        "ui-db-password": False,
        "ui-auth-secret": False,
        "adguard-core-password": False,
        "myst-consumer-passphrase": False,
        "nodeui-pass": True,
    }


def test_doctor_command_exit_codes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr(cli, "gather", lambda _box, **_kwargs: facts())
    result = runner.invoke(cli.app, ["doctor", "--dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "0 fail" in result.output
    monkeypatch.setattr(
        cli,
        "gather",
        lambda _box, **_kwargs: facts(docker_error="docker not found; run install.sh"),
    )
    result = runner.invoke(cli.app, ["doctor", "--dir", str(tmp_path), "--json"])
    assert result.exit_code == 1
    verdicts = {item["name"]: item["verdict"] for item in json.loads(result.output)}
    assert verdicts["docker"] == "fail"


def tunnel_facts(**overrides: object) -> dict[str, doctor.FileFact]:
    files = {
        "server.key": doctor.FileFact(present=True, mode=0o600),
        "wg0.conf": doctor.FileFact(present=True, mode=0o600),
    }
    files.update(overrides)  # type: ignore[arg-type]
    return files


def test_tunnel_verdicts_for_vps() -> None:
    def verdict(files: dict[str, doctor.FileFact], **extra: object) -> doctor.CheckResult:
        return by_name(evaluate(facts(config=vps_config(), tunnel=files, **extra)))["tunnel"]

    ok = verdict(tunnel_facts())
    assert ok.verdict is Verdict.OK and "mode 600" in ok.detail
    fresh = verdict(
        tunnel_facts(**{"server.key": doctor.FileFact(False), "wg0.conf": doctor.FileFact(False)})
    )
    assert fresh.verdict is Verdict.WARN and fresh.hint == "vibedpn up"
    assert "core creates them at start" in fresh.detail
    loose = verdict(tunnel_facts(**{"server.key": doctor.FileFact(True, 0o644)}))
    assert loose.verdict is Verdict.FAIL and loose.detail == "server.key readable by other users"
    closed = verdict(tunnel_facts(**{"wg0.conf": doctor.FileFact(None)}))
    assert closed.verdict is Verdict.WARN and closed.hint == "sudo vibedpn doctor"


def test_tunnel_verdict_only_for_vps_with_gathered_facts() -> None:
    assert "tunnel" not in by_name(evaluate(facts(tunnel=tunnel_facts())))
    assert "tunnel" not in by_name(evaluate(facts(config=vps_config())))


def test_tunnel_files_are_read_from_the_box(tmp_path: Path) -> None:
    assert doctor.tunnel_files(tmp_path) == {
        "server.key": doctor.FileFact(False),
        "wg0.conf": doctor.FileFact(False),
    }
    directory = tmp_path / "secrets" / "wg-server"
    directory.mkdir(parents=True)
    (directory / "server.key").write_text("k\n", encoding="utf-8")
    (directory / "server.key").chmod(0o640)
    assert doctor.tunnel_files(tmp_path)["server.key"] == doctor.FileFact(True, 0o640)


def test_core_must_listen_on_the_tunnel_address() -> None:
    def verdict(listeners: list[Listener] | None, **extra: object) -> doctor.CheckResult:
        checked = facts(config=vps_config(), listeners=listeners, **extra)
        return by_name(evaluate(checked))["tunnel access"]

    core = [
        Listener("tcp", "10.78.0.1", 4449, "vibedpn-core"),
        Listener("tcp", "10.78.0.1", 4480, "vibedpn-core"),
    ]
    ok = verdict(core)
    assert ok.verdict is Verdict.OK
    assert ok.detail == "node panel 10.78.0.1:4449 and core API 10.78.0.1:4480 for home boxes"
    anonymous = verdict(
        [Listener("tcp", "10.78.0.1", 4449, ""), Listener("tcp", "10.78.0.1", 4480, "")]
    )
    assert anonymous.verdict is Verdict.OK  # not root: ss cannot name the process
    missing = verdict([Listener("tcp", "127.0.0.1", 4480, "vibedpn-core"), core[0]])
    assert missing.verdict is Verdict.FAIL
    assert missing.detail == "nothing listens on 10.78.0.1:4480"
    assert "vibedpn logs core" in missing.hint
    stranger = verdict([core[0], Listener("tcp", "10.78.0.1", 4480, "nginx")])
    assert stranger.verdict is Verdict.FAIL
    assert stranger.detail == "10.78.0.1:4480 is held by nginx, not core"
    unknown = verdict(None, listeners_error="`ss` not found (install iproute2)")
    assert unknown.verdict is Verdict.WARN
    assert unknown.detail == "cannot check: `ss` not found (install iproute2)"
    assert "tunnel access" not in by_name(evaluate(facts(listeners=core)))  # a home box


def test_lan_ipv6_is_parsed_from_ip_json() -> None:
    # `ip -j -6 addr show dev eth0` shape: link-local only, then a global address as well.
    link_local = (
        '[{"ifname":"eth0","addr_info":[{"family":"inet6","local":"fe80::1","scope":"link"}]}]'
    )
    assert doctor.parse_global_ipv6(link_local) is False
    global_too = link_local.replace(
        '"scope":"link"}]',
        '"scope":"link"},{"family":"inet6","local":"2001:db8::5","scope":"global"}]',
    )
    assert doctor.parse_global_ipv6(global_too) is True
    assert doctor.parse_global_ipv6("[]") is False
    assert doctor.parse_global_ipv6("not json") is None


def test_lan_ipv6_verdict_only_in_full() -> None:
    full = Config.model_validate(
        {
            "version": 1,
            "role": "client",
            "network": {
                "lan_interface": "eth0",
                "lan_subnet": "192.168.1.0/24",
                "lan_address": "192.168.1.50",
            },
            "routing": {"mode": "full", "default_upstream": "vps"},
            "upstreams": {"vps": {"enabled": True}},
        }
    )
    leaking = by_name(evaluate(facts(config=full, lan_ipv6=True)))["ipv6"]
    assert leaking.verdict is Verdict.WARN and "RA/DHCPv6" in leaking.hint
    assert by_name(evaluate(facts(config=full, lan_ipv6=False)))["ipv6"].verdict is Verdict.OK
    assert by_name(evaluate(facts(config=full, lan_ipv6=None)))["ipv6"].verdict is Verdict.WARN
    assert "ipv6" not in by_name(evaluate(facts(lan_ipv6=True)))  # home in mode off


def full_client() -> Config:
    return Config.model_validate(
        {
            "version": 1,
            "role": "client",
            "network": {
                "lan_interface": "eth0",
                "lan_subnet": "192.168.1.0/24",
                "lan_address": "192.168.1.50",
            },
            "routing": {"mode": "full", "default_upstream": "vps"},
            "upstreams": {"vps": {"enabled": True}},
        }
    )


def test_exit_address_parsing() -> None:
    assert doctor.parse_exit_address("203.0.113.7\n") == "203.0.113.7"
    assert doctor.parse_exit_address("<html>") is None
    assert doctor.parse_exit_address("") is None


def test_exit_verdicts_compare_the_uplink_with_the_direct_address() -> None:
    direct = doctor.ExitFact("direct", "203.0.113.7")

    def names(*exits: doctor.ExitFact) -> dict[str, CheckResult]:
        return by_name(evaluate(facts(config=full_client(), exits=[direct, *exits])))

    through = names(doctor.ExitFact("vps", "198.51.100.20"))
    assert through["exit direct"].detail == "203.0.113.7"
    assert (
        through["exit vps"].verdict is Verdict.OK and through["exit vps"].detail == "198.51.100.20"
    )
    bypass = names(doctor.ExitFact("vps", "203.0.113.7"))["exit vps"]
    assert bypass.verdict is Verdict.FAIL and "bypasses the tunnel" in bypass.hint
    silent = names(doctor.ExitFact("vps", None, "wg-client is not running"))["exit vps"]
    assert silent.verdict is Verdict.FAIL and "not running" in silent.detail
    offline = by_name(
        evaluate(facts(config=full_client(), exits=[doctor.ExitFact("direct", None, "timed out")]))
    )["exit direct"]
    assert offline.verdict is Verdict.WARN


def test_dns_leak_is_a_warning_only_in_full() -> None:
    leak = by_name(evaluate(facts(config=full_client(), exits=[])))["dns leak"]
    assert leak.verdict is Verdict.WARN and "DoH" in leak.detail
    assert by_name(evaluate(facts(exits=[])))["dns leak"].verdict is Verdict.OK  # home, mode off


def test_without_network_nothing_is_asked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The exit probes are the only requests to the internet; gather must not even reach them."""

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("doctor probed the network without --network")

    monkeypatch.setattr(doctor, "_exits", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    gathered = gather(tmp_path)  # an empty directory: no config, and still no network
    assert gathered.exits is None
    assert not any(
        name.startswith(("exit", "dns leak"))
        for name in by_name(evaluate(facts(config=full_client())))
    )


def test_router_verdicts() -> None:
    def verdict(config: Config, **overrides: object) -> CheckResult:
        base: dict[str, object] = {
            "router_table": True,
            "router_rules": True,
            "router_docker_user": True,
            "uplink_routes": {"vps": True, "dpn": True},
            "last_resort_routes": {"vps": True, "dpn": True},
            "rp_filter": 2,
        }
        base.update(overrides)
        return by_name(evaluate(facts(config=config, **base)))["router"]

    home = home_config()
    assert verdict(home).verdict is Verdict.OK
    assert verdict(home).detail == "routing.mode off: LAN goes direct through the box"
    full = Config.model_validate(
        {
            "version": 1,
            "role": "client",
            "network": {
                "lan_interface": "eth0",
                "lan_subnet": "192.168.1.0/24",
                "lan_address": "192.168.1.50",
            },
            "routing": {"mode": "full", "default_upstream": "vps"},
            "upstreams": {"vps": {"enabled": True}},
        }
    )
    assert verdict(full).detail == "routing.mode full, uplinks in use: vps (10.77.0.10)"
    held = verdict(full, uplink_routes={"vps": False})
    assert held.verdict is Verdict.WARN and "kill switch" in held.detail
    assert held.hint == "vibedpn logs wg-client"
    no_kill_switch = verdict(full, last_resort_routes={"vps": False})
    assert no_kill_switch.verdict is Verdict.FAIL and "kill-switch route" in no_kill_switch.detail
    assert verdict(full, uplink_routes={"vps": None}).detail == "cannot read routing table 7710"
    # A device on dpn makes a second uplink in use, with its own kill switch to check.
    two = full.model_copy(
        update={
            "upstreams": full.upstreams.model_copy(
                update={"dpn": full.upstreams.dpn.model_copy(update={"enabled": True})}
            ),
            "devices": [
                DeviceConfig(name="laptop", mac="aa:bb:cc:dd:ee:03", policy=DevicePolicy.DPN)
            ],
        }
    )
    assert verdict(two).detail == (
        "routing.mode full, uplinks in use: vps (10.77.0.10), dpn (10.77.0.20)"
    )
    second = verdict(two, last_resort_routes={"vps": True, "dpn": False})
    assert second.verdict is Verdict.FAIL and "table 7720" in second.detail
    strict = verdict(full, rp_filter=1)
    assert strict.verdict is Verdict.FAIL and "rp_filter" in strict.detail
    assert verdict(full, router_table=False).verdict is Verdict.FAIL
    assert verdict(full, router_rules=False).verdict is Verdict.FAIL
    assert verdict(full, router_docker_user=False).verdict is Verdict.FAIL
    unknown = verdict(full, router_table=None, router_error="nft not found", is_root=False)
    assert unknown.verdict is Verdict.WARN and unknown.hint == "sudo vibedpn doctor"
    assert "router" not in by_name(evaluate(facts(config=vps_config())))


def test_tunnel_egress_verdicts() -> None:
    def verdict(**overrides: object) -> CheckResult:
        return by_name(evaluate(facts(config=vps_config(), firewall_table=True, **overrides)))[
            "tunnel egress"
        ]

    fine = verdict(egress_table=True, docker_user=True)
    assert fine.verdict is Verdict.OK
    assert fine.detail == "peers of 10.78.0.0/24 leave through this VPS"
    no_table = verdict(egress_table=False, docker_user=True)
    assert no_table.verdict is Verdict.FAIL and "inet vibedpn_egress" in no_table.detail
    closed = verdict(egress_table=True, docker_user=False)
    assert closed.verdict is Verdict.FAIL and "DOCKER-USER" in closed.detail
    unknown = verdict(
        egress_table=True,
        docker_user=None,
        docker_user_error="cannot read DOCKER-USER without root",
        is_root=False,
    )
    assert unknown.verdict is Verdict.WARN and unknown.hint == "sudo vibedpn doctor"
    unlisted = verdict(egress_table=None, egress_error="nft cannot list tables: not root")
    assert unlisted.verdict is Verdict.WARN
    assert "tunnel egress" not in by_name(evaluate(facts()))  # a home box has no tunnel server


def test_the_panel_name_is_published_only_with_dns() -> None:
    published = by_name(evaluate(facts()))["ui name"]
    assert published.verdict is Verdict.OK
    assert published.detail.startswith("http://vibedpn.lan -> 192.168.1.50")
    raw = parse_yaml(render_config(home_config()))
    assert isinstance(raw, dict)
    raw["dns"] = {"enabled": False}
    raw["ui"] = {"port": 8080, "host_name": "box.home"}
    silent = by_name(evaluate(facts(config=Config.model_validate(raw))))["ui name"]
    assert silent.verdict is Verdict.WARN
    assert "box.home is not published" in silent.detail
    assert "http://192.168.1.50:8080" in silent.hint


def test_a_full_panel_on_a_small_host_is_warned() -> None:
    assert "ui variant" not in by_name(evaluate(facts()))  # memory unknown: no verdict
    small = by_name(evaluate(facts(memory_bytes=2 * 1024**3)))["ui variant"]
    assert small.verdict is Verdict.WARN and "lite" in small.hint
    assert by_name(evaluate(facts(memory_bytes=8 * 1024**3)))["ui variant"].verdict is Verdict.OK


def test_the_lan_access_of_the_vps_tunnel_is_reported() -> None:
    raw = parse_yaml(render_config(build_config(Answers(Role.CLIENT, password="secret123"), LAN)))
    assert isinstance(raw, dict)
    line = by_name(evaluate(facts(config=Config.model_validate(raw))))["vps lan access"]
    assert line.verdict is Verdict.OK and line.detail.startswith("closed")
    assert "vps lan access" not in by_name(evaluate(facts()))  # home box without the vps uplink


def test_the_nat_of_the_node_is_judged_only_when_asked() -> None:
    assert "nat" not in by_name(evaluate(facts()))  # without --network nothing is asked
    assert by_name(evaluate(facts(nat="fullcone")))["nat"].verdict is Verdict.OK
    punch = by_name(evaluate(facts(nat="prcone")))["nat"]
    assert punch.verdict is Verdict.OK and "56000-56100" in punch.detail
    symmetric = by_name(evaluate(facts(nat="symmetric")))["nat"]
    assert symmetric.verdict is Verdict.WARN and "forward UDP 56000-56100" in symmetric.hint
    silent = by_name(evaluate(facts(nat_error="TequilAPI /nat/type: HTTP 500")))["nat"]
    assert silent.verdict is Verdict.WARN and "HTTP 500" in silent.detail


def gateway_config() -> Config:
    raw = home_config().model_dump(mode="json", exclude_none=True, exclude={"firewall"})
    raw["network"] |= {"mode": "gateway", "wan_interface": "eth1"}
    return Config.model_validate(raw)


def test_gateway_needs_dhcp_port_and_its_lan_address() -> None:
    needs = {(n.service, n.label) for n in port_needs(gateway_config())}
    assert ("dnsmasq", "udp/67") in needs
    assert ("dnsmasq", "udp/67") not in {(n.service, n.label) for n in port_needs(home_config())}
    missing = evaluate(facts(config=gateway_config(), lan_address_set=False))
    assert any(r.name == "lan address" and r.verdict is Verdict.FAIL for r in missing)
    present = evaluate(facts(config=gateway_config(), lan_address_set=True))
    assert any(r.name == "lan address" and r.verdict is Verdict.OK for r in present)
    assert not any(r.name == "lan address" for r in evaluate(facts()))
