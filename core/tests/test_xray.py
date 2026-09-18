"""Uplink xray: reading a share link and rendering what the gateway runs."""

import json

import pytest

from vibedpn.engine.xray import (
    REDIRECT_PORT,
    XrayError,
    config_from_link,
    parse_share_link,
    render_config,
)

REALITY = (
    "vless://11111111-2222-3333-4444-555555555555@exit.example.org:443"
    "?type=tcp&security=reality&sni=www.cloudflare.com&fp=chrome"
    "&pbk=AbCdEf0123456789&sid=9f1a&flow=xtls-rprx-vision#%D0%9C%D0%BE%D0%B9%20%D0%B2%D1%8B%D1%85%D0%BE%D0%B4"
)


def test_a_reality_link_is_read_field_by_field() -> None:
    server = parse_share_link(REALITY)
    assert server.uuid == "11111111-2222-3333-4444-555555555555"
    assert server.endpoint == "exit.example.org:443"
    assert (server.network, server.security) == ("tcp", "reality")
    assert server.sni == "www.cloudflare.com"
    assert server.public_key == "AbCdEf0123456789" and server.short_id == "9f1a"
    assert server.flow == "xtls-rprx-vision" and server.fingerprint == "chrome"
    # the remark is what the owner sees in their client, percent-encoded in the link
    assert server.remark == "Мой выход"


def test_the_rendered_configuration_carries_reality_and_no_way_out_besides_it() -> None:
    config = json.loads(config_from_link(REALITY))
    inbound = config["inbounds"][0]
    assert inbound["protocol"] == "dokodemo-door"
    assert inbound["port"] == REDIRECT_PORT and inbound["settings"]["followRedirect"] is True

    # One outbound and no freedom next to it: with the server unreachable the box drops the
    # traffic instead of letting it out past the tunnel.
    assert len(config["outbounds"]) == 1
    outbound = config["outbounds"][0]
    assert outbound["protocol"] == "vless"
    user = outbound["settings"]["vnext"][0]["users"][0]
    assert user["id"] == "11111111-2222-3333-4444-555555555555"
    assert user["flow"] == "xtls-rprx-vision" and user["encryption"] == "none"
    reality = outbound["streamSettings"]["realitySettings"]
    assert reality == {
        "serverName": "www.cloudflare.com",
        "publicKey": "AbCdEf0123456789",
        "shortId": "9f1a",
        "fingerprint": "chrome",
    }


def test_websocket_and_grpc_links_bring_their_own_settings() -> None:
    ws = parse_share_link(
        "vless://u@host.example:8443?type=ws&security=tls&path=%2Fray&host=cdn.example&alpn=h2,http/1.1"
    )
    assert ws.path == "/ray" and ws.host_header == "cdn.example" and ws.alpn == ("h2", "http/1.1")
    stream = json.loads(render_config(ws))["outbounds"][0]["streamSettings"]
    assert stream["wsSettings"] == {"path": "/ray", "headers": {"Host": "cdn.example"}}
    assert stream["tlsSettings"]["serverName"] == "host.example"  # no sni: the host stands for it
    assert stream["tlsSettings"]["alpn"] == ["h2", "http/1.1"]

    grpc = parse_share_link("vless://u@host.example:443?type=grpc&security=tls&serviceName=tunnel")
    grpc_stream = json.loads(render_config(grpc))["outbounds"][0]["streamSettings"]
    assert grpc_stream["grpcSettings"] == {"serviceName": "tunnel"}


def test_a_link_this_box_cannot_use_is_refused_by_name() -> None:
    cases = {
        "": "empty",
        "https://example.org": "share link",
        "vless://@host.example:443": "no user id",
        "vless://u@:443": "names no server",
        "vless://u@host.example": "port of the server",
        "vless://u@host.example:0": "port of the server",
        "vless://u@host.example:443?type=kcp": "transport",
        "vless://u@host.example:443?security=xtls": "security",
        # reality without the key of the server, or without the name it pretends to visit
        "vless://u@host.example:443?security=reality&sni=a.example": "pbk",
        "vless://u@host.example:443?security=reality&pbk=key": "sni",
    }
    for link, reason in cases.items():
        with pytest.raises(XrayError, match=reason):
            parse_share_link(link)


def test_a_plain_link_renders_without_tls_settings() -> None:
    stream = json.loads(config_from_link("vless://u@10.0.0.2:443"))["outbounds"][0][
        "streamSettings"
    ]
    assert stream == {"network": "tcp", "security": "none"}
