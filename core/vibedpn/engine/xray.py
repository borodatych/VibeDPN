"""Uplink ``xray``: a masking transport (VLESS over Reality and friends) as a gateway container.

Where WireGuard does not pass — a network that drops its handshake — a masking transport still
does. The owner brings a share link, the string their provider or their own server hands out; core
parses it here and renders the configuration the gateway runs. The link stays in ``secrets/`` and
never reaches the image, and the parsing is here rather than in the entrypoint because a shell
script cannot be unit-tested on thirty malformed links.

The share link format is the one Xray publishes: ``vless://<uuid>@<host>:<port>?<params>#<remark>``
(https://github.com/XTLS/Xray-core/discussions/716). Only what the gateway can actually carry is
accepted; anything else is refused by name, because a silently ignored parameter is a tunnel that
does not work for a reason nobody can see.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlsplit

# The dokodemo-door inbound of the rendered configuration; images/xray/entrypoint.sh redirects the
# TCP of the LAN to this port and the two numbers have to stay equal.
REDIRECT_PORT = 12345
# The user xray runs as in images/xray: the gateway is not root, so the configuration core
# renders has to belong to it by number — the same way AdGuard gets its data.
XRAY_UID = 7754
SHARE_SCHEME = "vless"
PORT_MAX = 65535
NETWORKS = ("tcp", "ws", "grpc")
SECURITIES = ("none", "tls", "reality")
DEFAULT_FINGERPRINT = "chrome"  # what the share link means when it carries no fp


class XrayError(ValueError):
    """A share link this box cannot use, with the reason the owner reads."""


@dataclass(frozen=True)
class XrayServer:
    """One server of the owner, as its share link describes it."""

    uuid: str
    host: str
    port: int
    network: str = "tcp"
    security: str = "none"
    sni: str = ""
    fingerprint: str = ""
    public_key: str = ""  # pbk: the REALITY key of the server
    short_id: str = ""  # sid
    flow: str = ""
    path: str = ""
    host_header: str = ""
    service_name: str = ""
    alpn: tuple[str, ...] = ()
    encryption: str = "none"
    remark: str = ""

    @property
    def endpoint(self) -> str:
        """What to show the owner: the server without a word of its credentials."""
        return f"{self.host}:{self.port}"


def _one(params: dict[str, list[str]], name: str, default: str = "") -> str:
    values = params.get(name) or []
    return values[0].strip() if values else default


def parse_share_link(link: str) -> XrayServer:
    """The server of a ``vless://`` share link. Every refusal names what is wrong with the link."""
    text = link.strip()
    if not text:
        raise XrayError("the share link is empty")
    parts = urlsplit(text)
    if parts.scheme != SHARE_SCHEME:
        raise XrayError(f"{parts.scheme or text[:16]!r} is not a {SHARE_SCHEME}:// share link")
    uuid = unquote(parts.username or "")
    if not uuid:
        raise XrayError("the share link carries no user id before '@'")
    host = parts.hostname or ""
    if not host:
        raise XrayError("the share link names no server")
    try:
        port = parts.port or 0
    except ValueError as exc:  # urlsplit raises on a port that is not a number
        raise XrayError(f"the port of the share link is not a number: {exc}") from None
    if not 0 < port <= PORT_MAX:
        raise XrayError(f"the share link needs a port of the server (1-{PORT_MAX})")

    params = parse_qs(parts.query, keep_blank_values=True)
    network = _one(params, "type", "tcp") or "tcp"
    if network not in NETWORKS:
        raise XrayError(f"transport {network!r} is not carried by this box ({', '.join(NETWORKS)})")
    security = _one(params, "security", "none") or "none"
    if security not in SECURITIES:
        raise XrayError(f"security {security!r} is not carried by this box"
                        f" ({', '.join(SECURITIES)})")  # fmt: skip
    sni = _one(params, "sni")
    public_key = _one(params, "pbk")
    if security == "reality" and not public_key:
        raise XrayError("a reality link without pbk (the key of the server) cannot connect")
    if security == "reality" and not sni:
        raise XrayError("a reality link without sni (the name it pretends to visit) cannot connect")
    alpn = tuple(item for item in _one(params, "alpn").split(",") if item)
    return XrayServer(
        uuid=uuid,
        host=host,
        port=port,
        network=network,
        security=security,
        sni=sni,
        fingerprint=_one(params, "fp", DEFAULT_FINGERPRINT) or DEFAULT_FINGERPRINT,
        public_key=public_key,
        short_id=_one(params, "sid"),
        flow=_one(params, "flow"),
        path=_one(params, "path"),
        host_header=_one(params, "host"),
        service_name=_one(params, "serviceName"),
        alpn=alpn,
        encryption=_one(params, "encryption", "none") or "none",
        remark=unquote(parts.fragment),
    )


def _stream_settings(server: XrayServer) -> dict[str, object]:
    settings: dict[str, object] = {"network": server.network, "security": server.security}
    if server.network == "ws":
        headers = {"Host": server.host_header} if server.host_header else {}
        settings["wsSettings"] = {"path": server.path or "/", "headers": headers}
    elif server.network == "grpc":
        settings["grpcSettings"] = {"serviceName": server.service_name}
    if server.security == "tls":
        tls: dict[str, object] = {
            "serverName": server.sni or server.host,
            "fingerprint": server.fingerprint,
        }
        if server.alpn:
            tls["alpn"] = list(server.alpn)
        settings["tlsSettings"] = tls
    elif server.security == "reality":
        settings["realitySettings"] = {
            "serverName": server.sni,
            "publicKey": server.public_key,
            "shortId": server.short_id,
            "fingerprint": server.fingerprint,
        }
    return settings


def render_config(server: XrayServer, redirect_port: int = REDIRECT_PORT) -> str:
    """The configuration of the gateway: everything that arrives goes to the server, and there is
    no second outbound — a box with nowhere to send the traffic must drop it, not let it out."""
    user: dict[str, object] = {"id": server.uuid, "encryption": server.encryption}
    if server.flow:
        user["flow"] = server.flow
    config = {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "tag": "redirect",
                "listen": "0.0.0.0",
                "port": redirect_port,
                "protocol": "dokodemo-door",
                "settings": {"network": "tcp", "followRedirect": True},
            }
        ],
        "outbounds": [
            {
                "tag": "proxy",
                "protocol": "vless",
                "settings": {
                    "vnext": [{"address": server.host, "port": server.port, "users": [user]}]
                },
                "streamSettings": _stream_settings(server),
            }
        ],
    }
    return json.dumps(config, indent=2, ensure_ascii=False) + "\n"


def config_from_link(link: str, redirect_port: int = REDIRECT_PORT) -> str:
    """The whole way from what the owner pasted to what the gateway reads."""
    return render_config(parse_share_link(link), redirect_port)
