"""Parsers of iproute2 JSON (fixtures captured from a Debian trixie container) and the probe."""

import subprocess
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path
from types import SimpleNamespace

import pytest

from vibedpn import detect
from vibedpn.detect import (
    DetectError,
    HostProbe,
    Interface,
    parse_default_route,
    parse_interface,
    parse_interfaces,
    parse_mem_total,
)

FIXTURES = Path(__file__).parent / "fixtures"
ROUTE = (FIXTURES / "ip_route_default.json").read_text(encoding="utf-8")
ADDR = (FIXTURES / "ip_addr.json").read_text(encoding="utf-8")


def test_parse_default_route_from_real_output() -> None:
    assert parse_default_route(ROUTE) == "eth0"


def test_parse_default_route_without_default() -> None:
    assert parse_default_route("[]") is None
    assert parse_default_route('[{"dst": "10.0.0.0/8", "dev": "eth1"}]') is None


def test_parse_interface_from_real_output() -> None:
    interface = parse_interface(ADDR, "eth0")
    assert interface == Interface("eth0", IPv4Address("172.17.0.2"), 16)
    assert interface.subnet == IPv4Network("172.17.0.0/16")


def test_parse_interface_skips_loopback_and_unknown() -> None:
    assert parse_interface(ADDR, "lo") is None  # scope host, not global
    assert parse_interface(ADDR, "wlan0") is None


def test_probe_reports_missing_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError("ip")

    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(DetectError, match="iproute2"):
        HostProbe().default_interface()


def test_wireguard_module_detection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(detect, "SYSFS_MODULES", tmp_path / "absent")
    monkeypatch.setattr(detect, "find_modprobe", lambda: None)
    assert HostProbe().wireguard_module_present() is None  # cannot tell without modprobe

    def says_no(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(detect, "find_modprobe", lambda: "/usr/sbin/modprobe")
    monkeypatch.setattr(subprocess, "run", says_no)
    assert HostProbe().wireguard_module_present() is False
    (tmp_path / "wireguard").mkdir()
    monkeypatch.setattr(detect, "SYSFS_MODULES", tmp_path)
    assert HostProbe().wireguard_module_present() is True


def test_find_modprobe_looks_in_sbin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sbin = tmp_path / "sbin"
    sbin.mkdir()
    fake = sbin / "modprobe"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    monkeypatch.setattr(detect, "SBIN_DIRS", (str(sbin),))
    assert detect.find_modprobe() == str(fake)


def test_probe_reports_failing_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(*_args: object, **_kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, ["ip"], stderr="boom")

    monkeypatch.setattr(subprocess, "run", failing)
    with pytest.raises(DetectError, match="boom"):
        HostProbe().default_interface()


def test_mem_total_is_read_in_kib() -> None:
    meminfo = "MemTotal:        3884292 kB\nMemFree:          123456 kB\n"
    assert parse_mem_total(meminfo) == 3884292 * 1024
    assert parse_mem_total("MemFree: 1 kB\n") is None
    assert parse_mem_total("MemTotal: many kB\n") is None


def test_every_interface_with_a_global_address() -> None:
    text = (FIXTURES / "ip_addr.json").read_text(encoding="utf-8")
    names = [interface.name for interface in parse_interfaces(text)]
    assert "lo" not in names and "eth0" in names
