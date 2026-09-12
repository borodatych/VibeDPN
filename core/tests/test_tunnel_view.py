"""The peer table and QR code of `vibedpn peer`."""

from datetime import UTC, datetime
from ipaddress import IPv4Address

import pytest

from vibedpn.api.models import PeerView
from vibedpn.tunnel_view import handshake_text, qr_code, render_peers

NOW = 1_789_240_000


def view(name: str, **live: object) -> PeerView:
    return PeerView(
        name=name,
        address=IPv4Address("10.78.0.2"),
        public_key="pub",
        created=datetime(2026, 9, 12, tzinfo=UTC),
        **live,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("latest", "expected"),
    [
        (None, "?"),
        (0, "never"),
        (NOW - 5, "5s ago"),
        (NOW - 125, "2m ago"),
        (NOW - 3 * 3600, "3h ago"),
        (NOW - 2 * 86400, "2d ago"),
        (NOW + 30, "0s ago"),  # clocks disagree a little: not "in the future"
    ],
)
def test_handshake_text(latest: int | None, expected: str) -> None:
    assert handshake_text(latest, NOW) == expected


def test_table_is_aligned_and_honest_about_live_state() -> None:
    lines = render_peers(
        [
            view(
                "dacha",
                endpoint="203.0.113.7:40312",
                latest_handshake=NOW - 90,
                rx_bytes=1536,
                tx_bytes=10,
            ),
            view("flat-in-town", latest_handshake=0, rx_bytes=0, tx_bytes=0),
        ],
        NOW,
    )
    assert lines[0].split() == ["NAME", "ADDRESS", "HANDSHAKE", "RX", "TX", "ENDPOINT"]
    assert lines[1].startswith("dacha         10.78.0.2  1m ago")
    assert "1.5 KiB" in lines[1] and lines[1].endswith("203.0.113.7:40312")
    assert "never" in lines[2] and lines[2].endswith("-")
    assert len(lines) == 3


def test_table_says_when_core_cannot_read_the_interface() -> None:
    lines = render_peers([view("dacha")], NOW)
    assert "?" in lines[1]
    assert lines[-1].startswith("live state unavailable")


def test_no_peers_says_how_to_add_one() -> None:
    assert render_peers([], NOW) == ["no peers yet (add a home box: vibedpn peer add <name>)"]


def test_qr_code_is_a_block_picture() -> None:
    code = qr_code("[Interface]\nPrivateKey = x\n")
    rows = code.splitlines()
    assert len(rows) > 10
    assert any(block in code for block in ("█", "▀", "▄"))
