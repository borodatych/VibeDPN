"""Building and writing a box configuration from answers and host facts."""

import stat
from ipaddress import IPv4Address
from pathlib import Path

import bcrypt
import pytest

from vibedpn.bootstrap import (
    Answers,
    BootstrapError,
    HostFacts,
    build_config,
    image_tag_of,
    public_address,
    render_config,
    render_env,
    write_box,
)
from vibedpn.config import Config, Role, load_config, parse_yaml
from vibedpn.detect import Interface

LAN = HostFacts(Interface("eth0", IPv4Address("192.168.1.50"), 24), wireguard_module=True)
PUBLIC = HostFacts(Interface("ens3", IPv4Address("185.199.108.1"), 24), wireguard_module=True)
NOTHING = HostFacts(None, wireguard_module=False)


def test_public_address_only_for_global_ips() -> None:
    assert public_address(PUBLIC) == "185.199.108.1"
    assert public_address(LAN) is None
    assert public_address(NOTHING) is None
    # Documentation (TEST-NET) and CGNAT ranges are not globally routable either.
    for address in ("203.0.113.7", "100.64.0.1"):
        facts = HostFacts(Interface("ens3", IPv4Address(address), 24), wireguard_module=True)
        assert public_address(facts) is None


def test_home_config_from_detected_lan() -> None:
    config = build_config(Answers(Role.HOME, password="secret123"), LAN)
    assert config.role is Role.HOME
    assert config.network is not None
    assert str(config.network.lan_subnet) == "192.168.1.0/24"
    assert config.routing is not None
    assert config.routing.mode.value == "off"
    assert config.routing.default_upstream.value == "dpn"
    assert config.upstreams.dpn.enabled and config.provider.enabled
    assert [p.value for p in config.compose_profiles()] == [
        "provider",
        "consumer",
        "router",
        "dns",
        "ui",
    ]


def test_client_config_uses_vps_uplink() -> None:
    config = build_config(Answers(Role.CLIENT, password="x" * 8, peer_config=Path("p.conf")), LAN)
    assert config.upstreams.vps.enabled and not config.upstreams.dpn.enabled
    assert config.routing is not None
    assert config.routing.default_upstream.value == "vps"
    assert not config.provider.enabled


def test_vps_config_detects_public_endpoint() -> None:
    config = build_config(Answers(Role.VPS), PUBLIC)
    assert config.wg_server is not None
    assert config.wg_server.endpoint == "185.199.108.1"
    assert config.network is None and config.routing is None


def test_vps_config_needs_endpoint_behind_nat() -> None:
    with pytest.raises(BootstrapError, match="--endpoint"):
        build_config(Answers(Role.VPS), LAN)
    config = build_config(Answers(Role.VPS, endpoint="vps.example.com"), LAN)
    assert config.wg_server is not None
    assert config.wg_server.endpoint == "vps.example.com"


def test_lan_roles_need_an_interface() -> None:
    with pytest.raises(BootstrapError, match="default route"):
        build_config(Answers(Role.HOME, password="secret123"), NOTHING)


@pytest.mark.parametrize("role", [Role.HOME, Role.CLIENT, Role.VPS])
def test_rendered_config_round_trips(role: Role) -> None:
    facts = PUBLIC if role is Role.VPS else LAN
    config = build_config(Answers(role, password="secret123", peer_config=Path("p")), facts)
    assert Config.model_validate(parse_yaml(render_config(config))) == config


def test_render_env_lists_every_derived_variable() -> None:
    config = build_config(Answers(Role.HOME, password="secret123"), LAN)
    text = render_env(config, image_tag="next")
    for key, value in config.env_vars().items():
        assert f"{key}={value}\n" in text
    assert "VIBEDPN_TAG=next\n" in text


def test_image_tag_survives_reinit(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    assert image_tag_of(env) == "latest"
    env.write_text("COMPOSE_PROFILES=provider\nVIBEDPN_TAG=v0.2.0\n", encoding="utf-8")
    assert image_tag_of(env) == "v0.2.0"


def test_write_box_writes_config_env_and_secrets(tmp_path: Path) -> None:
    peer = tmp_path / "home.conf"
    peer.write_text("[Interface]\nPrivateKey = x\n", encoding="utf-8")
    answers = Answers(Role.CLIENT, password="secret123", peer_config=peer)
    config = build_config(answers, LAN)
    box = tmp_path / "box"
    written = write_box(box, config, answers, force=False)
    assert [p.name for p in written] == ["config.yaml", ".env", "htpasswd", "wg-client.conf"]
    assert load_config(box / "config.yaml") == config
    assert stat.S_IMODE((box / "secrets").stat().st_mode) == 0o700
    assert stat.S_IMODE((box / "secrets" / "htpasswd").stat().st_mode) == 0o600
    assert stat.S_IMODE((box / "secrets" / "wg-client.conf").stat().st_mode) == 0o600
    user, digest = (box / "secrets" / "htpasswd").read_text(encoding="utf-8").strip().split(":", 1)
    assert user == "admin"
    assert bcrypt.checkpw(b"secret123", digest.encode("ascii"))
    assert (box / "secrets" / "wg-client.conf").read_text(encoding="utf-8") == peer.read_text(
        encoding="utf-8"
    )
    assert "COMPOSE_PROFILES=wg-client,router,dns,ui" in (box / ".env").read_text(encoding="utf-8")


def test_write_box_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    answers = Answers(Role.VPS)
    config = build_config(answers, PUBLIC)
    write_box(tmp_path, config, answers, force=False)
    (tmp_path / ".env").write_text("VIBEDPN_TAG=v9\n", encoding="utf-8")
    with pytest.raises(BootstrapError, match="--force"):
        write_box(tmp_path, config, answers, force=False)
    written = write_box(tmp_path, config, answers, force=True)
    assert [p.name for p in written] == ["config.yaml", ".env"]
    assert (tmp_path / "config.yaml.bak").is_file()
    assert "VIBEDPN_TAG=v9" in (tmp_path / ".env").read_text(encoding="utf-8")
    assert not (tmp_path / "secrets" / "htpasswd").exists()


def test_write_box_reports_unreadable_peer_file(tmp_path: Path) -> None:
    answers = Answers(Role.CLIENT, password="secret123", peer_config=tmp_path / "missing.conf")
    with pytest.raises(BootstrapError, match="cannot read"):
        write_box(tmp_path / "box", build_config(answers, LAN), answers, force=False)
