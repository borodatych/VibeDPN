"""Networks of routing.lists: the router declares their sets, core fills them"""

from ipaddress import IPv4Address, IPv4Network
from typing import Any

import dns.message

from vibedpn.config import Config
from vibedpn.engine.resolver import (
    Resolver,
    RuleIndex,
    list_network_sets,
    networks_script,
)
from vibedpn.engine.router import exit_for, router_ruleset, smart_list_networks

from .conftest import home_config

LIST = "https://community.antifilter.download/list/community.lst"
DIRECT_LIST = "https://lists.example/direct.lst"


def smart_box(**routing: object) -> Config:
    raw: dict[str, Any] = home_config()
    raw["upstreams"]["tor"] = {"enabled": True}
    raw["routing"] = {
        "mode": "smart",
        "default_upstream": "dpn",
        "lists": [{"url": LIST, "via": "tor"}, {"url": DIRECT_LIST, "via": "direct"}],
        **routing,
    }
    return Config.model_validate(raw)


def no_upstream(_query: dns.message.Message) -> dns.message.Message:
    raise AssertionError("nothing is resolved here")


def test_the_router_declares_a_set_per_list_channel_and_matches_it_after_the_network_rules() -> (
    None
):
    config = smart_box(networks=[{"network": "149.154.160.0/20", "via": "tor"}])
    assert list_network_sets(config) == ["smart_direct_lnet", "smart_tor_lnet"]
    assert [(item.name, item.mark) for item in smart_list_networks(config)] == [
        ("smart_direct_lnet", ""),
        ("smart_tor_lnet", "0x60"),
    ]
    text = router_ruleset(config)
    assert text is not None
    steer = text.split("chain steer {")[1]
    order = [
        steer.index(rule) for rule in ("@smart_tor_net", "@smart_direct_lnet", "@smart_tor_lnet")
    ]
    assert order == sorted(order)  # the owner's own networks first, a direct list before the others
    assert "set smart_tor_lnet {\n    type ipv4_addr\n    flags interval\n  }" in text
    off = smart_box(mode="off")
    rendered = router_ruleset(off)
    assert rendered is not None and "@smart_tor_lnet" not in rendered.split("chain steer {")[1]
    assert "set smart_tor_lnet" in rendered  # declared in every mode: core fills it all the same


def test_core_fills_each_set_with_the_merged_networks_of_its_lists() -> None:
    scripts: list[str] = []
    config = smart_box()
    resolver = Resolver(RuleIndex.from_config(config), no_upstream, scripts.append)
    networks = {
        LIST: [IPv4Network("198.18.0.0/25"), IPv4Network("198.18.0.128/25")],
        DIRECT_LIST: [IPv4Network("203.0.113.0/24")],
    }
    resolver.set_lists(config, {LIST: ["rutracker.org"]}, networks)
    assert networks_script("smart_tor_lnet", [IPv4Network("198.18.0.0/24")]) in scripts
    assert networks_script("smart_direct_lnet", [IPv4Network("203.0.113.0/24")]) in scripts
    assert resolver.index.match("rutracker.org") == "smart_tor"  # the domains of a list stay
    assert resolver.listed(IPv4Address("198.18.0.200")) == "smart_tor"
    assert resolver.listed(IPv4Address("192.0.2.1")) is None
    scripts.clear()
    resolver.set_lists(config, {}, {})  # the lists lost their networks: the sets are emptied
    assert scripts[-2:] == [
        "flush set inet vibedpn_router smart_direct_lnet\n",
        "flush set inet vibedpn_router smart_tor_lnet\n",
    ]


def test_the_bot_goes_the_way_a_list_network_sends_a_device() -> None:
    config = smart_box(networks=[{"network": "198.18.0.0/28", "via": "direct"}])

    def listed(address: IPv4Address) -> str | None:
        return "smart_tor" if address in IPv4Network("198.18.0.0/24") else None

    assert exit_for(config, None, IPv4Address("198.18.0.50"), listed) == "tor"
    # the owner's own network rule is matched before the list, as in the chain steer
    assert exit_for(config, None, IPv4Address("198.18.0.5"), listed) is None
    assert exit_for(config, None, IPv4Address("192.0.2.1"), listed) is None
