"""WireGuard keys and the server config that core renders for role vps."""

import base64
import os
from ipaddress import IPv4Address, IPv4Interface
from pathlib import Path

import pytest

from vibedpn.config import Config
from vibedpn.engine import wg
from vibedpn.engine.wg import (
    SERVER_CONF_FILE,
    SERVER_DIR,
    SERVER_KEY_FILE,
    Peer,
    WgError,
    clamp,
    decode_key,
    ensure_server,
    generate_private_key,
    public_key,
    render_server_conf,
    server_address,
    write_private,
)

from .conftest import home_config, vps_config

# RFC 7748 §6.1, Alice: X25519(a, 9) — the published vector, as WireGuard base64.
RFC_PRIVATE = base64.b64encode(
    bytes.fromhex("77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a")
).decode()
RFC_PUBLIC = base64.b64encode(
    bytes.fromhex("8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a")
).decode()


def vps(**wg_server: object) -> Config:
    raw = vps_config()
    raw["wg_server"] = {**raw["wg_server"], **wg_server}
    return Config.model_validate(raw)


def mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def test_public_key_matches_rfc_7748_vector() -> None:
    assert public_key(RFC_PRIVATE) == RFC_PUBLIC


def test_clamp_sets_the_curve25519_bits() -> None:
    clamped = clamp(bytes([0xFF] * 32))
    assert clamped[0] == 0xF8
    assert clamped[31] == 0x7F
    assert clamp(bytes(32))[31] == 0x40


def test_generated_keys_look_like_wg_genkey() -> None:
    first, second = generate_private_key(), generate_private_key()
    assert first != second
    raw = decode_key(first)
    assert len(first) == 44 and len(raw) == 32
    assert raw == clamp(raw)
    assert len(decode_key(public_key(first))) == 32


@pytest.mark.parametrize(
    ("text", "reason"),
    [("not base64 at all!", "not a base64"), (base64.b64encode(b"short").decode(), "32 bytes")],
)
def test_decode_key_rejects_what_wg_would_reject(text: str, reason: str) -> None:
    with pytest.raises(WgError, match=reason):
        decode_key(text)


def test_server_takes_the_first_host_of_the_subnet() -> None:
    assert server_address(vps()) == IPv4Interface("10.78.0.1/24")
    assert server_address(vps(subnet="10.50.0.0/16")) == IPv4Interface("10.50.0.1/16")


def test_render_without_peers() -> None:
    text = render_server_conf(vps(listen_port=51999), RFC_PRIVATE)
    assert "[Interface]\nAddress = 10.78.0.1/24\nListenPort = 51999\n" in text
    assert f"PrivateKey = {RFC_PRIVATE}\n" in text
    assert "[Peer]" not in text


def test_render_with_peers() -> None:
    peers = [
        Peer("dacha", RFC_PUBLIC, IPv4Address("10.78.0.2")),
        Peer("flat", RFC_PUBLIC, IPv4Address("10.78.0.3")),
    ]
    text = render_server_conf(vps(), RFC_PRIVATE, peers)
    assert text.count("[Peer]") == 2
    assert f"[Peer]\n# dacha\nPublicKey = {RFC_PUBLIC}\nAllowedIPs = 10.78.0.2/32\n" in text
    assert "AllowedIPs = 10.78.0.3/32" in text


def test_roles_without_a_server_render_nothing(tmp_path: Path) -> None:
    home = Config.model_validate(home_config())
    assert ensure_server(home, tmp_path) is None
    assert not (tmp_path / SERVER_DIR).exists()
    with pytest.raises(WgError, match="no WireGuard server"):
        render_server_conf(home, RFC_PRIVATE)


def test_first_start_creates_a_private_key_and_config(tmp_path: Path) -> None:
    conf = ensure_server(vps(), tmp_path)
    directory = tmp_path / SERVER_DIR
    key_file = directory / SERVER_KEY_FILE
    assert conf == directory / SERVER_CONF_FILE
    assert (mode(directory), mode(key_file), mode(conf)) == (0o700, 0o600, 0o600)
    key = key_file.read_text(encoding="utf-8").strip()
    decode_key(key)
    assert f"PrivateKey = {key}\n" in conf.read_text(encoding="utf-8")
    assert not [p for p in directory.iterdir() if p.name.startswith(".")]  # no temp leftovers


def test_restart_keeps_the_key_and_leaves_an_unchanged_config_alone(tmp_path: Path) -> None:
    ensure_server(vps(), tmp_path)
    directory = tmp_path / SERVER_DIR
    key = (directory / SERVER_KEY_FILE).read_text(encoding="utf-8")
    inode = (directory / SERVER_CONF_FILE).stat().st_ino
    ensure_server(vps(), tmp_path)
    assert (directory / SERVER_KEY_FILE).read_text(encoding="utf-8") == key
    assert (directory / SERVER_CONF_FILE).stat().st_ino == inode


def test_config_change_rewrites_the_config_with_the_same_key(tmp_path: Path) -> None:
    ensure_server(vps(), tmp_path)
    directory = tmp_path / SERVER_DIR
    key = (directory / SERVER_KEY_FILE).read_text(encoding="utf-8")
    ensure_server(vps(listen_port=51999), tmp_path)
    assert "ListenPort = 51999" in (directory / SERVER_CONF_FILE).read_text(encoding="utf-8")
    assert (directory / SERVER_KEY_FILE).read_text(encoding="utf-8") == key


def test_loose_modes_are_tightened(tmp_path: Path) -> None:
    ensure_server(vps(), tmp_path)
    directory = tmp_path / SERVER_DIR
    directory.chmod(0o755)
    (directory / SERVER_KEY_FILE).chmod(0o644)
    (directory / SERVER_CONF_FILE).chmod(0o644)
    ensure_server(vps(), tmp_path)
    assert mode(directory) == 0o700
    assert mode(directory / SERVER_KEY_FILE) == 0o600
    assert mode(directory / SERVER_CONF_FILE) == 0o600


def test_a_broken_key_is_never_replaced(tmp_path: Path) -> None:
    directory = tmp_path / SERVER_DIR
    directory.mkdir(mode=0o700)
    (directory / SERVER_KEY_FILE).write_text("garbage\n", encoding="utf-8")
    with pytest.raises(WgError, match="restore it from a backup"):
        ensure_server(vps(), tmp_path)
    assert (directory / SERVER_KEY_FILE).read_text(encoding="utf-8") == "garbage\n"
    assert not (directory / SERVER_CONF_FILE).exists()


def test_unwritable_secrets_is_a_readable_error(tmp_path: Path) -> None:
    secrets_file = tmp_path / "secrets"
    secrets_file.write_text("not a directory", encoding="utf-8")
    with pytest.raises(WgError, match="cannot write the tunnel files"):
        ensure_server(vps(), secrets_file)


def test_a_failed_write_leaves_the_old_file_and_no_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "wg0.conf"
    target.write_text("old\n", encoding="utf-8")

    def broken_fdopen(*_args: object, **_kwargs: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "fdopen", broken_fdopen)
    with pytest.raises(OSError, match="No space left"):
        write_private(target, "new\n")
    assert target.read_text(encoding="utf-8") == "old\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["wg0.conf"]


def test_write_private_reports_whether_it_wrote(tmp_path: Path) -> None:
    target = tmp_path / "wg0.conf"
    assert write_private(target, "a\n") is True
    assert write_private(target, "a\n") is False
    assert write_private(target, "b\n") is True


def test_module_constants_match_the_image_contract() -> None:
    """compose.yaml mounts secrets/wg-server as /etc/wireguard; the entrypoint reads wg0.conf."""
    compose = (Path(__file__).parents[2] / "compose.yaml").read_text(encoding="utf-8")
    assert f"./secrets/{wg.SERVER_DIR}:/etc/wireguard:ro" in compose
    entrypoint = (Path(__file__).parents[2] / "images" / "wg" / "entrypoint.sh").read_text(
        encoding="utf-8"
    )
    assert f"CONF=/etc/wireguard/{wg.SERVER_CONF_FILE}" in entrypoint
