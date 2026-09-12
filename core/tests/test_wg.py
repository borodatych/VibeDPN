"""WireGuard keys and the server config that core renders for role vps."""

import base64
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from ipaddress import IPv4Address, IPv4Interface
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from vibedpn.atomic import write_private
from vibedpn.bootstrap import read_peer_config
from vibedpn.config import Config, parse_yaml
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


def peer(name: str, address: str) -> Peer:
    return Peer(
        name=name,
        address=IPv4Address(address),
        public_key=RFC_PUBLIC,
        private_key=RFC_PRIVATE,
        created=datetime(2026, 9, 12, tzinfo=UTC),
    )


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
    peers = [peer("dacha", "10.78.0.2"), peer("flat", "10.78.0.3")]
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
    files = ensure_server(vps(), tmp_path)
    assert files is not None and files.renumbered == ()
    conf = files.conf
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


def test_wg_server_waits_for_core_to_render_its_config() -> None:
    """Without the condition compose starts wg-server next to core, and it reads a stale file."""
    compose = cast(
        "dict[str, Any]",
        parse_yaml((Path(__file__).parents[2] / "compose.yaml").read_text(encoding="utf-8")),
    )
    assert compose["services"]["wg-server"]["depends_on"]["core"]["condition"] == "service_healthy"


def test_write_private_flushes_the_file_and_the_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synced: list[int] = []
    real_fsync = os.fsync

    def recording_fsync(descriptor: int) -> None:
        synced.append(descriptor)
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    write_private(tmp_path / "server.key", "key\n")
    assert len(synced) == 2  # the temporary file before the rename, the directory after it
    synced.clear()
    write_private(tmp_path / "server.key", "key\n")
    assert synced == []  # unchanged content: nothing written, nothing to flush


# --- the peer registry --------------------------------------------------------------------


def registry_file(tmp_path: Path) -> Path:
    return tmp_path / SERVER_DIR / wg.PEERS_FILE


def test_first_peer_takes_the_address_after_the_server(tmp_path: Path) -> None:
    added = wg.add_peer(vps(), tmp_path, "dacha")
    assert added.address == IPv4Address("10.78.0.2")
    assert public_key(added.private_key) == added.public_key
    assert mode(registry_file(tmp_path)) == 0o600
    conf = (tmp_path / SERVER_DIR / SERVER_CONF_FILE).read_text(encoding="utf-8")
    assert f"[Peer]\n# dacha\nPublicKey = {added.public_key}\nAllowedIPs = 10.78.0.2/32\n" in conf


@pytest.mark.parametrize("name", ["", "Dacha", "-box", "box_2", "x/y", "a" * 33, "дача"])
def test_bad_peer_names_are_refused(tmp_path: Path, name: str) -> None:
    with pytest.raises(wg.PeerNameError, match="not a peer name"):
        wg.add_peer(vps(), tmp_path, name)
    assert not registry_file(tmp_path).exists()


@pytest.mark.parametrize("name", ["dacha", "box-2", "7", "a" * 32])
def test_good_peer_names_are_accepted(tmp_path: Path, name: str) -> None:
    assert wg.add_peer(vps(), tmp_path, name).name == name


def test_a_name_is_registered_once(tmp_path: Path) -> None:
    wg.add_peer(vps(), tmp_path, "dacha")
    with pytest.raises(wg.PeerExistsError, match="already exists"):
        wg.add_peer(vps(), tmp_path, "dacha")
    assert [p.name for p in wg.list_peers(vps(), tmp_path)] == ["dacha"]


def test_a_full_subnet_is_a_clear_error(tmp_path: Path) -> None:
    small = vps(subnet="10.78.0.0/30")  # hosts .1 (server) and .2
    assert wg.add_peer(small, tmp_path, "only").address == IPv4Address("10.78.0.2")
    with pytest.raises(wg.SubnetFullError, match="every address"):
        wg.add_peer(small, tmp_path, "second")


def test_a_removed_peer_frees_its_address(tmp_path: Path) -> None:
    wg.add_peer(vps(), tmp_path, "first")
    wg.add_peer(vps(), tmp_path, "second")
    removed = wg.remove_peer(vps(), tmp_path, "first")
    assert removed.address == IPv4Address("10.78.0.2")
    assert wg.add_peer(vps(), tmp_path, "third").address == IPv4Address("10.78.0.2")
    conf = (tmp_path / SERVER_DIR / SERVER_CONF_FILE).read_text(encoding="utf-8")
    assert "# first" not in conf and "# second" in conf and "# third" in conf


def test_removing_an_unknown_peer_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(wg.PeerNotFoundError, match="no peer named 'ghost'"):
        wg.remove_peer(vps(), tmp_path, "ghost")


def test_a_damaged_registry_is_never_reset(tmp_path: Path) -> None:
    ensure_server(vps(), tmp_path)
    registry_file(tmp_path).write_text("{not json", encoding="utf-8")
    with pytest.raises(WgError, match="restore it from a backup"):
        ensure_server(vps(), tmp_path)
    with pytest.raises(WgError, match="restore it from a backup"):
        wg.add_peer(vps(), tmp_path, "dacha")
    assert registry_file(tmp_path).read_text(encoding="utf-8") == "{not json"


def test_registry_refuses_duplicate_names_or_addresses() -> None:
    twin = peer("dacha", "10.78.0.2")
    with pytest.raises(ValueError, match="appears twice"):
        wg.PeerRegistry(peers=[twin, twin])


def test_concurrent_adds_get_distinct_addresses(tmp_path: Path) -> None:
    """The API serves requests from a thread pool; the registry must not lose or share writes."""
    ensure_server(vps(), tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        added = list(pool.map(lambda i: wg.add_peer(vps(), tmp_path, f"box-{i}"), range(12)))
    assert len({p.address for p in added}) == 12
    assert len(wg.list_peers(vps(), tmp_path)) == 12


def test_client_conf_is_what_a_home_box_installs(tmp_path: Path) -> None:
    added = wg.add_peer(vps(), tmp_path, "dacha")
    text = wg.peer_config(vps(), tmp_path, "dacha")
    server_key = (tmp_path / SERVER_DIR / SERVER_KEY_FILE).read_text(encoding="utf-8").strip()
    assert "[Interface]\n" in text
    assert f"PrivateKey = {added.private_key}\nAddress = 10.78.0.2/32\n" in text
    assert f"PublicKey = {public_key(server_key)}\n" in text
    assert "Endpoint = vps.example.com:51820\n" in text
    assert "AllowedIPs = 0.0.0.0/0\nPersistentKeepalive = 25\n" in text
    assert server_key not in text  # the server's own key never leaves the VPS
    peer_file = tmp_path / "dacha.conf"
    peer_file.write_text(text, encoding="utf-8")
    assert read_peer_config(peer_file) == text


def test_exporting_an_unknown_peer_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(wg.PeerNotFoundError):
        wg.peer_config(vps(), tmp_path, "ghost")


# --- the live interface ------------------------------------------------------------------

DUMP = (Path(__file__).parent / "fixtures" / "wg" / "show_dump.txt").read_text(encoding="utf-8")


def test_dump_is_parsed_without_keeping_the_interface_line() -> None:
    links = wg.parse_wg_dump(DUMP)
    assert sorted(links) == [
        "3p7bfXt9wbTTW2HC7OQ1Nz+DQ8hbeGdNrfx+FG+IK08=",
        "hSDwCYkwp1R0i33ctD73Wg2/Og0mOBr066SpjqqbTmo=",
    ]
    idle = links["hSDwCYkwp1R0i33ctD73Wg2/Og0mOBr066SpjqqbTmo="]
    assert idle == wg.PeerLink(endpoint=None, latest_handshake=0, rx_bytes=0, tx_bytes=0)
    busy = links["3p7bfXt9wbTTW2HC7OQ1Nz+DQ8hbeGdNrfx+FG+IK08="]
    assert busy == wg.PeerLink("203.0.113.7:40312", 1789236372, 15432, 9876)
    interface_private_key = DUMP.split("\t", 1)[0]
    assert all(interface_private_key not in str(link) for link in links.values())


def test_read_wg_dump_degrades_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wg, "find_tool", lambda _name: None)
    assert wg.read_wg_dump() is None
    monkeypatch.setattr(wg, "find_tool", lambda _name: "/usr/bin/wg")
    monkeypatch.setattr(
        subprocess, "run", lambda *_a, **_k: SimpleNamespace(returncode=1, stdout="", stderr="")
    )
    assert wg.read_wg_dump() is None
    monkeypatch.setattr(
        subprocess, "run", lambda *_a, **_k: SimpleNamespace(returncode=0, stdout=DUMP, stderr="")
    )
    links = wg.read_wg_dump()
    assert links is not None and len(links) == 2


# --- subnet changes and failed writes ------------------------------------------------------


def test_a_changed_subnet_moves_peers_and_keeps_their_keys(tmp_path: Path) -> None:
    first = wg.add_peer(vps(), tmp_path, "dacha")
    second = wg.add_peer(vps(), tmp_path, "flat")
    moved_config = vps(subnet="10.99.0.0/24")
    files = ensure_server(moved_config, tmp_path)
    assert files is not None
    assert files.renumbered == (
        wg.Renumbered("dacha", IPv4Address("10.78.0.2"), IPv4Address("10.99.0.2")),
        wg.Renumbered("flat", IPv4Address("10.78.0.3"), IPv4Address("10.99.0.3")),
    )
    moved = {p.name: p for p in wg.list_peers(moved_config, tmp_path)}
    assert moved["dacha"].private_key == first.private_key
    assert moved["flat"].public_key == second.public_key
    conf = files.conf.read_text(encoding="utf-8")
    assert "Address = 10.99.0.1/24" in conf and "AllowedIPs = 10.99.0.2/32" in conf
    assert "10.78." not in conf
    assert "Address = 10.99.0.2/32" in wg.peer_config(moved_config, tmp_path, "dacha")
    again = ensure_server(moved_config, tmp_path)
    assert again is not None and again.renumbered == ()


def test_a_peer_on_the_server_address_is_moved(tmp_path: Path) -> None:
    ensure_server(vps(), tmp_path)
    registry_file(tmp_path).write_text(
        wg.PeerRegistry(peers=[peer("dacha", "10.78.0.1")]).model_dump_json(), encoding="utf-8"
    )
    files = ensure_server(vps(), tmp_path)
    assert files is not None
    assert files.renumbered == (
        wg.Renumbered("dacha", IPv4Address("10.78.0.1"), IPv4Address("10.78.0.2")),
    )


def test_a_subnet_too_small_for_the_registry_is_a_clear_error(tmp_path: Path) -> None:
    wg.add_peer(vps(), tmp_path, "dacha")
    wg.add_peer(vps(), tmp_path, "flat")
    before = registry_file(tmp_path).read_text(encoding="utf-8")
    with pytest.raises(WgError, match="room for 1 peers, the registry has 2"):
        ensure_server(vps(subnet="10.99.0.0/30"), tmp_path)
    assert registry_file(tmp_path).read_text(encoding="utf-8") == before


def test_a_failed_registry_write_puts_the_old_config_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wg.add_peer(vps(), tmp_path, "dacha")
    conf_path = tmp_path / SERVER_DIR / SERVER_CONF_FILE
    conf_before = conf_path.read_text(encoding="utf-8")
    registry_before = registry_file(tmp_path).read_text(encoding="utf-8")

    def failing_registry(path: Path, content: str) -> bool:
        if path.name == wg.PEERS_FILE:
            raise OSError(28, "No space left on device")
        return write_private(path, content)

    monkeypatch.setattr("vibedpn.engine.wg.write_private", failing_registry)
    with pytest.raises(WgError, match="No space left on device"):
        wg.add_peer(vps(), tmp_path, "flat")
    assert conf_path.read_text(encoding="utf-8") == conf_before
    assert registry_file(tmp_path).read_text(encoding="utf-8") == registry_before
    monkeypatch.setattr("vibedpn.engine.wg.write_private", write_private)
    assert wg.add_peer(vps(), tmp_path, "flat").name == "flat"  # a retry is not a 409


def test_a_failed_config_write_leaves_the_registry_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wg.add_peer(vps(), tmp_path, "dacha")
    registry_before = registry_file(tmp_path).read_text(encoding="utf-8")

    def failing_conf(path: Path, content: str) -> bool:
        if path.name == SERVER_CONF_FILE:
            raise OSError(5, "Input/output error")
        return write_private(path, content)

    monkeypatch.setattr("vibedpn.engine.wg.write_private", failing_conf)
    with pytest.raises(WgError, match="Input/output error"):
        wg.remove_peer(vps(), tmp_path, "dacha")
    assert registry_file(tmp_path).read_text(encoding="utf-8") == registry_before


def test_export_never_creates_a_server_key(tmp_path: Path) -> None:
    wg.add_peer(vps(), tmp_path, "dacha")
    key_file = tmp_path / SERVER_DIR / SERVER_KEY_FILE
    key_file.unlink()
    with pytest.raises(WgError, match="is missing; core creates the server key at start"):
        wg.peer_config(vps(), tmp_path, "dacha")
    assert not key_file.exists()


def test_a_tunnel_only_peer_routes_only_the_tunnel_subnet(tmp_path: Path) -> None:
    laptop = wg.add_peer(vps(), tmp_path, "laptop", tunnel_only=True)
    box = wg.add_peer(vps(), tmp_path, "dacha")
    assert laptop.tunnel_only and not box.tunnel_only
    assert "AllowedIPs = 10.78.0.0/24\n" in wg.peer_config(vps(), tmp_path, "laptop")
    assert "AllowedIPs = 0.0.0.0/0\n" in wg.peer_config(vps(), tmp_path, "dacha")
    stored = {p.name: p.tunnel_only for p in wg.list_peers(vps(), tmp_path)}
    assert stored == {"laptop": True, "dacha": False}
    moved = vps(subnet="10.99.0.0/24")
    ensure_server(moved, tmp_path)
    assert "AllowedIPs = 10.99.0.0/24\n" in wg.peer_config(moved, tmp_path, "laptop")


def test_registries_written_before_tunnel_only_still_load(tmp_path: Path) -> None:
    ensure_server(vps(), tmp_path)
    old = peer("dacha", "10.78.0.2").model_dump(mode="json")
    del old["tunnel_only"]
    registry_file(tmp_path).write_text(
        '{"version": 1, "peers": [' + __import__("json").dumps(old) + "]}", encoding="utf-8"
    )
    assert wg.list_peers(vps(), tmp_path)[0].tunnel_only is False
