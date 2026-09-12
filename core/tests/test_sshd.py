"""sshd port detection for the VPS firewall."""

from pathlib import Path

from vibedpn.detect import parse_sshd_includes, parse_sshd_ports, sshd_ports

FIXTURE = Path(__file__).parent / "fixtures" / "sshd"


def test_parse_ports_skips_comments_and_match_blocks() -> None:
    text = (FIXTURE / "sshd_config").read_text(encoding="utf-8")
    assert parse_sshd_ports(text) == [2222]
    assert parse_sshd_ports("port 22\nPort 22\nPort 2200\n") == [22, 2200]
    assert parse_sshd_ports("Port abc\n") == []


def test_parse_includes() -> None:
    text = (FIXTURE / "sshd_config").read_text(encoding="utf-8")
    assert parse_sshd_includes(text) == ["/etc/ssh/sshd_config.d/*.conf"]


def test_sshd_ports_follow_includes_in_lexical_order(tmp_path: Path) -> None:
    root = tmp_path / "ssh"
    root.mkdir()
    (root / "sshd_config.d").mkdir()
    (root / "sshd_config").write_text("Include sshd_config.d/*.conf\nPort 2222\n", encoding="utf-8")
    (root / "sshd_config.d" / "20-b.conf").write_text("Port 3333\n", encoding="utf-8")
    (root / "sshd_config.d" / "10-a.conf").write_text("Port 4444\nPort 2222\n", encoding="utf-8")
    assert sshd_ports(root / "sshd_config", root) == [2222, 4444, 3333]


def test_sshd_ports_defaults_to_22(tmp_path: Path) -> None:
    assert sshd_ports(tmp_path / "missing", tmp_path) == [22]
    (tmp_path / "sshd_config").write_text("PasswordAuthentication no\n", encoding="utf-8")
    assert sshd_ports(tmp_path / "sshd_config", tmp_path) == [22]
