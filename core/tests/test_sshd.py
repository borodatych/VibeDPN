"""sshd port detection for the VPS firewall: config files and ``sshd -T``."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from vibedpn import detect
from vibedpn.detect import (
    HostProbe,
    listen_address_port,
    parse_sshd_includes,
    parse_sshd_ports,
    sshd_directives,
    sshd_effective_ports,
    sshd_ports,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sshd"


def test_parse_ports_skips_comments_and_match_blocks() -> None:
    text = (FIXTURE / "sshd_config").read_text(encoding="utf-8")
    assert parse_sshd_ports(text) == [2222]
    assert parse_sshd_ports("port 22\nPort 22\nPort 2200\n") == [22, 2200]
    assert parse_sshd_ports("Port abc\n") == [22]  # nothing usable: a stock sshd listens on 22


@pytest.mark.parametrize(
    "text",
    [
        "Port 2222\n",
        "Port\t2222\n",
        "Port=2222\n",
        "Port = 2222\n",
        'Port "2222"\n',
        "Port 2222\nMatch\tUser backup\n\tPort 9999\n",
        "Port 2222\nMatch=User backup\n  Port 9999\n",
    ],
)
def test_tokenizer_reads_lines_like_sshd(text: str) -> None:
    """sshd splits at whitespace or one ``=``; ``Match`` starts a block whatever follows it."""
    assert parse_sshd_ports(text) == [2222]


def test_directives_lowercase_keywords_and_unquote_values() -> None:
    assert sshd_directives('PermitRootLogin "no"\n# comment\n\nPort=22\n') == [
        ("permitrootlogin", "no"),
        ("port", "22"),
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0.0.0.0:2222", 2222),
        ("vps.example.com:2222", 2222),
        ("[::]:2200", 2200),
        ("[2001:db8::1]:2200 rdomain 1", 2200),
        ("10.0.0.1", None),
        ("2001:db8::1", None),
        ("[2001:db8::1]", None),
        ("0.0.0.0:abc", None),
        ("", None),
    ],
)
def test_listen_address_port(value: str, expected: int | None) -> None:
    assert listen_address_port(value) == expected


def test_listen_address_with_a_port_pins_it() -> None:
    assert parse_sshd_ports("ListenAddress 203.0.113.7:2222\n") == [2222]
    assert parse_sshd_ports("ListenAddress [::1]:2200 rdomain 1\nPort 22\n") == [2200]
    # Without a port a ListenAddress listens on every Port value.
    assert parse_sshd_ports("ListenAddress 10.0.0.1\nPort 2222\n") == [2222]
    assert parse_sshd_ports("ListenAddress 10.0.0.1\n") == [22]
    assert parse_sshd_ports("ListenAddress 10.0.0.1\nListenAddress [::1]:2200\nPort 22\n") == [
        2200,
        22,
    ]


def test_parse_includes() -> None:
    text = (FIXTURE / "sshd_config").read_text(encoding="utf-8")
    assert parse_sshd_includes(text) == ["/etc/ssh/sshd_config.d/*.conf"]
    assert parse_sshd_includes("Include\tsshd_config.d/*.conf\nInclude=extra.conf\n") == [
        "sshd_config.d/*.conf",
        "extra.conf",
    ]


def test_sshd_ports_follow_includes_in_lexical_order(tmp_path: Path) -> None:
    root = tmp_path / "ssh"
    root.mkdir()
    (root / "sshd_config.d").mkdir()
    (root / "sshd_config").write_text("Include sshd_config.d/*.conf\nPort 2222\n", encoding="utf-8")
    (root / "sshd_config.d" / "20-b.conf").write_text("Port 3333\n", encoding="utf-8")
    (root / "sshd_config.d" / "10-a.conf").write_text("Port 4444\nPort 2222\n", encoding="utf-8")
    # The Include stands first, so its files' ports come first (lexical order among them).
    assert sshd_ports(root / "sshd_config", root) == [4444, 2222, 3333]


def test_included_files_are_read_at_the_include_line(tmp_path: Path) -> None:
    """sshd inserts an Include where it stands, so a trailing Match block hides nothing."""
    root = tmp_path / "ssh"
    (root / "sshd_config.d").mkdir(parents=True)
    (root / "sshd_config").write_text(
        "Include sshd_config.d/*.conf\nPort 2222\nMatch User backup\n  Port 9999\n",
        encoding="utf-8",
    )
    (root / "sshd_config.d" / "10-a.conf").write_text("Port 4444\n", encoding="utf-8")
    assert sshd_ports(root / "sshd_config", root) == [4444, 2222]
    (root / "sshd_config").write_text(
        "Include sshd_config.d/*.conf\nMatch User backup\n  Port 9999\n", encoding="utf-8"
    )
    (root / "sshd_config.d" / "10-a.conf").write_text(
        "ListenAddress 0.0.0.0:2222\n", encoding="utf-8"
    )
    assert sshd_ports(root / "sshd_config", root) == [2222]


def test_nested_includes_stop_at_the_depth_sshd_allows(tmp_path: Path) -> None:
    (tmp_path / "loop.conf").write_text("Include loop.conf\nPort 2222\n", encoding="utf-8")
    assert sshd_ports(tmp_path / "loop.conf", tmp_path) == [2222]


def test_sshd_ports_defaults_to_22(tmp_path: Path) -> None:
    assert sshd_ports(tmp_path / "missing", tmp_path) == [22]
    (tmp_path / "sshd_config").write_text("PasswordAuthentication no\n", encoding="utf-8")
    assert sshd_ports(tmp_path / "sshd_config", tmp_path) == [22]


# ``sshd -T`` as printed by OpenSSH 9.6 for Port 22 plus Port 2222 (lowercase, one space,
# a listenaddress line per port and address family).
SSHD_T = (
    "port 22\nport 2222\nlistenaddress [::]:22\nlistenaddress 0.0.0.0:22\n"
    "listenaddress [::]:2222\nlistenaddress 0.0.0.0:2222\n"
)


def test_sshd_t_output_is_read_by_the_same_parser() -> None:
    assert parse_sshd_ports(SSHD_T) == [22, 2222]
    # An explicit ListenAddress with a port: sshd -T prints only it, Port 22 is not listened on.
    assert parse_sshd_ports("port 22\nlistenaddress 0.0.0.0:2200\n") == [2200]


def test_effective_ports_come_from_sshd_t(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout=SSHD_T, stderr="")

    monkeypatch.setattr(detect, "find_tool", lambda name: "/usr/sbin/sshd")
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert sshd_effective_ports() == [22, 2222]
    assert calls == [["/usr/sbin/sshd", "-T"]]


def test_effective_ports_are_none_without_a_cooperative_sshd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(detect, "find_tool", lambda name: None)
    assert sshd_effective_ports() is None

    def refuses(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=1, stdout="", stderr="no hostkeys available")

    monkeypatch.setattr(detect, "find_tool", lambda name: "/usr/sbin/sshd")
    monkeypatch.setattr(subprocess, "run", refuses)
    assert sshd_effective_ports() is None


def test_probe_prefers_the_daemon_and_falls_back_to_files(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(detect, "sshd_effective_ports", lambda: [2222])
    monkeypatch.setattr(detect, "sshd_ports", lambda: [22])
    assert HostProbe().ssh_ports() == [2222]
    monkeypatch.setattr(detect, "sshd_effective_ports", lambda: None)
    assert HostProbe().ssh_ports() == [22]
