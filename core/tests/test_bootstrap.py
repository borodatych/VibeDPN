"""Building and writing a box configuration from answers and host facts."""

import os
import stat
import subprocess
from ipaddress import IPv4Address
from pathlib import Path

import bcrypt
import pytest

from vibedpn import bootstrap
from vibedpn.bootstrap import (
    GENERATED_SECRETS,
    Answers,
    BootstrapError,
    HostFacts,
    build_config,
    check_password,
    checkout_image_tag,
    preserved_env,
    public_address,
    read_peer_config,
    render_config,
    render_env,
    required_secrets,
    ui_variant_for,
    write_box,
)
from vibedpn.config import Config, Role, UiVariant, load_config, parse_yaml
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
    assert config.routing.default_upstream == "dpn"
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
    assert config.routing.default_upstream == "vps"
    assert not config.provider.enabled


def test_vps_config_detects_public_endpoint() -> None:
    config = build_config(Answers(Role.VPS), PUBLIC)
    assert config.wg_server is not None
    assert config.wg_server.endpoint == "185.199.108.1"
    assert config.network is None and config.routing is None
    assert config.firewall.ssh_ports == [22]
    custom = HostFacts(PUBLIC.interface, True, ssh_ports=[2222, 22])
    assert build_config(Answers(Role.VPS), custom).firewall.ssh_ports == [2222, 22]


def test_vps_config_needs_endpoint_behind_nat() -> None:
    with pytest.raises(BootstrapError, match="--endpoint"):
        build_config(Answers(Role.VPS), LAN)
    config = build_config(Answers(Role.VPS, endpoint="vps.example.com"), LAN)
    assert config.wg_server is not None
    assert config.wg_server.endpoint == "vps.example.com"


def test_vps_config_rejects_bad_endpoint_readably() -> None:
    with pytest.raises(BootstrapError, match="without a port"):
        build_config(Answers(Role.VPS, endpoint="vps.example.com:51820"), LAN)


def test_password_policy() -> None:
    check_password("secret123")
    check_password("x" * 72)
    with pytest.raises(BootstrapError, match="at least 8"):
        check_password("short")
    with pytest.raises(BootstrapError, match="72 bytes"):
        check_password("x" * 73)
    with pytest.raises(BootstrapError, match="72 bytes"):
        check_password("п" * 37)  # 74 bytes of UTF-8


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
    text = render_env(config, {"VIBEDPN_TAG": "next", "MYST_TAG": "1.40.0-alpine"})
    for key, value in config.env_vars().items():
        assert f"{key}={value}\n" in text
    assert "VIBEDPN_TAG=next\n" in text
    assert "MYST_TAG=1.40.0-alpine\n" in text


def test_preserved_env_keeps_tags_only(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    assert preserved_env(env) == {"VIBEDPN_TAG": "latest"}
    env.write_text(
        "COMPOSE_PROFILES=provider\nVIBEDPN_TAG=v0.2.0\nADGUARD_TAG=v0.108.0\nJUNK=1\n",
        encoding="utf-8",
    )
    assert preserved_env(env) == {"VIBEDPN_TAG": "v0.2.0", "ADGUARD_TAG": "v0.108.0"}


def test_write_box_writes_config_env_and_secrets(tmp_path: Path) -> None:
    peer = tmp_path / "home.conf"
    peer.write_text("[Interface]\nPrivateKey = x\n", encoding="utf-8")
    answers = Answers(Role.CLIENT, password="secret123", peer_config=peer)
    config = build_config(answers, LAN)
    box = tmp_path / "box"
    written = write_box(box, config, answers, force=False)
    assert [p.name for p in written.files] == [
        "config.yaml",
        ".env",
        "htpasswd",
        "wg-client.conf",
        "ui-db-password",
        "ui-auth-secret",
        "adguard-core-password",
    ]
    assert written.retired == []
    for name in ("ui-db-password", "ui-auth-secret"):
        generated = box / "secrets" / name
        assert stat.S_IMODE(generated.stat().st_mode) == 0o600
        assert len(generated.read_text(encoding="utf-8")) >= 32
        assert not generated.read_text(encoding="utf-8").endswith("\n")
    assert not (box / "data").exists()  # a client runs no node
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


def test_write_box_writes_the_node_password_for_provider_roles(tmp_path: Path) -> None:
    for answers in (
        Answers(Role.HOME, password="secret123"),
        Answers(Role.VPS, password="secret123", endpoint="vps.example.com"),
    ):
        box = tmp_path / answers.role.value
        written = write_box(box, build_config(answers, LAN), answers, force=False)
        node_pass = box / "data" / "myst-provider" / "nodeui-pass"
        assert node_pass in written.files
        assert stat.S_IMODE(node_pass.stat().st_mode) == 0o600
        digest = node_pass.read_text(encoding="utf-8").strip()
        assert digest.startswith("$2b$") and bcrypt.checkpw(b"secret123", digest.encode("ascii"))


def test_write_box_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    answers = Answers(Role.VPS)  # no password: nothing secret is written
    config = build_config(answers, PUBLIC)
    write_box(tmp_path, config, answers, force=False)
    (tmp_path / ".env").write_text("VIBEDPN_TAG=v9\n", encoding="utf-8")
    with pytest.raises(BootstrapError, match="--force"):
        write_box(tmp_path, config, answers, force=False)
    written = write_box(tmp_path, config, answers, force=True)
    assert [p.name for p in written.files] == ["config.yaml", ".env"]
    assert (tmp_path / "config.yaml.bak").is_file()
    assert "VIBEDPN_TAG=v9" in (tmp_path / ".env").read_text(encoding="utf-8")
    assert not (tmp_path / "secrets" / "htpasswd").exists()


def test_write_box_gathers_everything_before_writing(tmp_path: Path) -> None:
    box = tmp_path / "box"
    answers = Answers(Role.CLIENT, password="secret123", peer_config=tmp_path / "missing.conf")
    with pytest.raises(BootstrapError, match="cannot read"):
        write_box(box, build_config(answers, LAN), answers, force=False)
    assert not box.exists()
    binary = tmp_path / "blob.conf"
    binary.write_bytes(b"\xff\xfe\x00")
    answers = Answers(Role.CLIENT, password="secret123", peer_config=binary)
    with pytest.raises(BootstrapError, match="not a UTF-8"):
        write_box(box, build_config(answers, LAN), answers, force=False)
    assert not box.exists()
    long_password = Answers(Role.HOME, password="п" * 37)
    with pytest.raises(BootstrapError, match="72 bytes"):
        write_box(box, build_config(long_password, LAN), long_password, force=False)
    assert not box.exists()


def test_read_peer_config_sanity(tmp_path: Path) -> None:
    not_a_peer = tmp_path / "notes.conf"
    not_a_peer.write_text("hello\n", encoding="utf-8")
    with pytest.raises(BootstrapError, match="Interface"):
        read_peer_config(not_a_peer)


def test_force_with_a_new_role_sets_old_secrets_aside(tmp_path: Path) -> None:
    peer = tmp_path / "home.conf"
    peer.write_text("[Interface]\nPrivateKey = x\n", encoding="utf-8")
    client = Answers(Role.CLIENT, password="secret123", peer_config=peer)
    box = tmp_path / "box"
    write_box(box, build_config(client, LAN), client, force=False)
    vps = Answers(Role.VPS, endpoint="vps.example.com")
    written = write_box(box, build_config(vps, LAN), vps, force=True)
    assert sorted(p.name for p in written.retired) == [
        "adguard-core-password.bak",
        "htpasswd.bak",
        "ui-auth-secret.bak",
        "ui-db-password.bak",
        "wg-client.conf.bak",
    ]
    assert not (box / "secrets" / "wg-client.conf").exists()
    assert stat.S_IMODE((box / "secrets" / "wg-client.conf.bak").stat().st_mode) == 0o600
    # A node password left behind by a provider role is set aside the same way.
    node = Answers(Role.VPS, password="secret123", endpoint="vps.example.com")
    write_box(box, build_config(node, LAN), node, force=True)
    back = write_box(box, build_config(client, LAN), client, force=True)
    assert [p.name for p in back.retired] == ["nodeui-pass.bak"]
    assert not (box / "data" / "myst-provider" / "nodeui-pass").exists()


def test_write_box_reports_unwritable_directory(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir(mode=0o500)
    answers = Answers(Role.VPS, endpoint="vps.example.com")
    try:
        with pytest.raises(BootstrapError, match="sudo"):
            write_box(locked / "box", build_config(answers, LAN), answers, force=False)
    finally:
        locked.chmod(0o700)


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_checkout_image_tag_follows_the_branch(tmp_path: Path) -> None:
    assert checkout_image_tag(tmp_path) == "latest"  # not a checkout at all
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(
        repo,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "x",
    )
    assert checkout_image_tag(repo) == "latest"
    git(repo, "switch", "-q", "-c", "next")
    assert checkout_image_tag(repo) == "next"
    git(repo, "switch", "-q", "-c", "feature/wifi")
    assert checkout_image_tag(repo) == "feature-wifi"
    git(repo, "switch", "-q", "--detach")
    assert checkout_image_tag(repo) == "latest"


def test_preserved_env_takes_the_default_tag(tmp_path: Path) -> None:
    assert preserved_env(tmp_path / ".env", "next") == {"VIBEDPN_TAG": "next"}


def test_init_under_sudo_hands_top_level_files_to_the_invoker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chowned: list[tuple[Path, int, int]] = []
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(os, "chown", lambda path, uid, gid: chowned.append((Path(path), uid, gid)))
    monkeypatch.setenv("SUDO_UID", "1000")
    monkeypatch.setenv("SUDO_GID", "1000")
    answers = Answers(Role.HOME, password="secret123")
    box = tmp_path / "box"
    write_box(box, build_config(answers, LAN), answers, force=False)
    assert sorted(p.name for p, _, _ in chowned) == [".env", "config.yaml"]
    assert all((uid, gid) == (1000, 1000) for _, uid, gid in chowned)


def test_no_ownership_change_without_sudo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    called = []
    monkeypatch.setattr(os, "chown", lambda *a: called.append(a))
    monkeypatch.delenv("SUDO_UID", raising=False)
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    assert bootstrap.invoker_ids() is None
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    monkeypatch.setenv("SUDO_UID", "1000")
    monkeypatch.setenv("SUDO_GID", "1000")
    assert bootstrap.invoker_ids() is None
    answers = Answers(Role.VPS, endpoint="vps.example.com")
    write_box(tmp_path / "box", build_config(answers, LAN), answers, force=False)
    assert called == []


def test_generated_secrets_survive_a_forced_re_run(tmp_path: Path) -> None:
    answers = Answers(Role.HOME, password="secret123")
    config = build_config(answers, LAN)
    write_box(tmp_path, config, answers, force=False)
    secrets = tmp_path / "secrets"
    before = {
        name: (secrets / name).read_text(encoding="utf-8")
        for name in GENERATED_SECRETS
        if (secrets / name).exists()
    }
    assert before["ui-db-password"] != before["ui-auth-secret"]
    written = write_box(tmp_path, config, Answers(Role.HOME, password="another123"), force=True)
    assert not {p.name for p in written.files} & set(GENERATED_SECRETS)
    after = {
        name: (secrets / name).read_text(encoding="utf-8")
        for name in GENERATED_SECRETS
        if (secrets / name).exists()
    }
    assert after == before
    (secrets / "ui-auth-secret").write_text("", encoding="utf-8")  # empty counts as absent
    written = write_box(tmp_path, config, answers, force=True)
    assert [p.name for p in written.files if p.name in GENERATED_SECRETS] == ["ui-auth-secret"]
    assert (secrets / "ui-db-password").read_text(encoding="utf-8") == before["ui-db-password"]


def test_the_panel_secrets_are_required_only_with_the_ui() -> None:
    home = build_config(Answers(Role.HOME, password="secret123"), LAN)
    assert required_secrets(home) == [
        "htpasswd",
        "nodeui-pass",
        "ui-db-password",
        "ui-auth-secret",
        "adguard-core-password",
        "myst-consumer-passphrase",
    ]
    vps = build_config(Answers(Role.VPS, endpoint="vps.example.com"), PUBLIC)
    assert "ui-db-password" not in required_secrets(vps)


def test_the_panel_variant_follows_the_memory_unless_given() -> None:
    small = HostFacts(LAN.interface, wireguard_module=True, memory_bytes=2 * 1024**3)
    big = HostFacts(LAN.interface, wireguard_module=True, memory_bytes=8 * 1024**3)
    client = Answers(Role.CLIENT, password="secret123")
    assert ui_variant_for(client, small) is UiVariant.LITE
    assert ui_variant_for(client, big) is UiVariant.FULL
    assert ui_variant_for(client, LAN) is UiVariant.FULL  # memory unknown
    forced = Answers(Role.CLIENT, password="secret123", ui_variant=UiVariant.FULL)
    assert ui_variant_for(forced, small) is UiVariant.FULL
    assert (
        build_config(Answers(Role.HOME, password="secret123"), small).ui.variant is UiVariant.LITE
    )
    assert build_config(client, small).ui.variant is UiVariant.LITE
