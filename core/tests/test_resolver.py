"""The resolver of core for routing.mode smart: rules to sets, TTL and set lifetime, CNAME and
learned CDNs following their site, replay after the router rebuilt its table."""

import asyncio

import dns.message
import dns.rcode
import dns.rrset

from vibedpn.config import Config
from vibedpn.engine.resolver import (
    MAX_ANSWER_TTL,
    SET_MARGIN_SECONDS,
    Resolver,
    ResolverError,
    ResolverProtocol,
    RuleIndex,
    answer_facts,
    channel_set,
    fill_script,
    smart_set_names,
)
from vibedpn.engine.router import router_ruleset

from .conftest import client_config


def smart_box() -> Config:
    raw = client_config()
    raw["upstreams"]["dpn"] = {"enabled": True}
    raw["routing"]["domains"] = [
        {"domain": "kinopoisk.ru", "via": "dpn", "country": "DE"},
        {"domain": "netflix.com", "via": "vps", "also": ["nflxvideo.net"]},
        {"domain": "bank.example", "via": "direct"},
        {"domain": "bbc.co.uk", "via": "dpn"},
    ]
    return Config.model_validate(raw)


def answer(query: dns.message.Message, *records: tuple[str, int, str, str]) -> dns.message.Message:
    response = dns.message.make_response(query)
    for name, ttl, kind, value in records:
        response.answer.append(dns.rrset.from_text(name, ttl, "IN", kind, value))
    return response


class Upstream:
    def __init__(self, *records: tuple[str, int, str, str]) -> None:
        self.records = records
        self.asked: list[str] = []

    def __call__(self, query: dns.message.Message) -> dns.message.Message:
        self.asked.append(query.question[0].name.to_text())
        return answer(query, *self.records)


class Nft:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, script: str) -> None:
        self.calls.append(script)


def test_rules_map_to_channel_sets() -> None:
    config = smart_box()
    rules = {rule.domain: channel_set(rule) for rule in config.routing.domains}  # type: ignore[union-attr]
    assert rules == {
        "kinopoisk.ru": "smart_dpn_de",
        "netflix.com": "smart_vps",
        "bank.example": "smart_direct",
        "bbc.co.uk": "smart_dpn_any",
    }
    assert smart_set_names(config) == ["smart_direct", "smart_dpn_any", "smart_dpn_de", "smart_vps"]
    ruleset = router_ruleset(config) or ""
    assert "set smart_dpn_de {\n    type ipv4_addr\n    flags timeout\n  }" in ruleset


def test_the_longest_suffix_wins_and_subdomains_match() -> None:
    index = RuleIndex([("example.com", "smart_vps"), ("cdn.example.com", "smart_direct")])
    assert index.match("www.example.com.") == "smart_vps"
    assert index.match("a.cdn.example.com") == "smart_direct"
    assert index.match("example.org") is None
    assert index.match("com") is None


def test_a_rule_name_fills_its_set_with_a_capped_ttl() -> None:
    nft = Nft()
    upstream = Upstream(("www.kinopoisk.ru.", 3600, "A", "203.0.113.5"))
    resolver = Resolver(RuleIndex.from_config(smart_box()), upstream, nft)
    response = resolver.resolve(dns.message.make_query("www.kinopoisk.ru", "A"))
    assert response.answer[0].ttl == MAX_ANSWER_TTL
    assert nft.calls == [
        fill_script("smart_dpn_de", ["203.0.113.5"], MAX_ANSWER_TTL + SET_MARGIN_SECONDS)
    ]


def test_a_name_under_no_rule_is_passed_through_untouched() -> None:
    nft = Nft()
    upstream = Upstream(("example.org.", 3600, "A", "198.51.100.1"))
    resolver = Resolver(RuleIndex.from_config(smart_box()), upstream, nft)
    response = resolver.resolve(dns.message.make_query("example.org", "A"))
    assert response.answer[0].ttl == 3600 and nft.calls == []


def test_a_cdn_behind_a_cname_follows_its_site() -> None:
    nft = Nft()
    upstream = Upstream(
        ("video.kinopoisk.ru.", 120, "CNAME", "edge.strm-cdn.net."),
        ("edge.strm-cdn.net.", 60, "A", "203.0.113.9"),
    )
    resolver = Resolver(RuleIndex.from_config(smart_box()), upstream, nft)
    resolver.resolve(dns.message.make_query("video.kinopoisk.ru", "A"))
    assert nft.calls == [fill_script("smart_dpn_de", ["203.0.113.9"], 60 + SET_MARGIN_SECONDS)]
    assert resolver.index.match("edge.strm-cdn.net") == "smart_dpn_de"
    assert resolver.cnames == {"edge.strm-cdn.net": "video.kinopoisk.ru"}


def test_a_learned_cdn_fills_its_set_from_the_last_answer_at_once() -> None:
    now = [1000.0]
    nft = Nft()
    upstream = Upstream(("strm.yandex.net.", 200, "A", "203.0.113.20"))
    resolver = Resolver(RuleIndex.from_config(smart_box()), upstream, nft, clock=lambda: now[0])
    resolver.resolve(dns.message.make_query("strm.yandex.net", "A"))
    assert nft.calls == []  # not under a rule yet: direct
    now[0] += 50
    assert resolver.learn("strm.yandex.net", "www.kinopoisk.ru") is True
    assert nft.calls == [fill_script("smart_dpn_de", ["203.0.113.20"], 150 + SET_MARGIN_SECONDS)]
    assert resolver.learn("x.example", "example.org") is False


def test_replay_refills_the_sets_after_the_router_rebuilt_them() -> None:
    now = [0.0]
    nft = Nft()
    upstream = Upstream(("netflix.com.", 100, "A", "198.51.100.7"))
    resolver = Resolver(RuleIndex.from_config(smart_box()), upstream, nft, clock=lambda: now[0])
    resolver.resolve(dns.message.make_query("netflix.com", "A"))
    nft.calls.clear()
    now[0] = 40
    resolver.replay()
    assert nft.calls == [fill_script("smart_vps", ["198.51.100.7"], 60 + SET_MARGIN_SECONDS)]
    now[0] = 200  # the answer expired: nothing to replay
    nft.calls.clear()
    resolver.replay()
    assert nft.calls == []


def test_a_fill_is_one_transaction_that_renews_the_timeout() -> None:
    target = "element inet vibedpn_router smart_vps"
    timed = "{ 192.0.2.1 timeout 360s, 192.0.2.2 timeout 360s }"
    assert fill_script("smart_vps", ["192.0.2.1", "192.0.2.2"], 360) == (
        f"add {target} {timed}\ndelete {target} {{ 192.0.2.1, 192.0.2.2 }}\nadd {target} {timed}\n"
    )


def test_answer_facts_read_addresses_targets_and_ttl() -> None:
    query = dns.message.make_query("a.example", "A")
    facts = answer_facts(
        answer(
            query, ("a.example.", 30, "CNAME", "b.example."), ("b.example.", 90, "A", "192.0.2.1")
        )
    )
    assert (facts.addresses, facts.cname_targets, facts.ttl) == (["192.0.2.1"], ["b.example"], 30)


def test_a_failing_upstream_answers_servfail() -> None:
    def broken(_query: dns.message.Message) -> dns.message.Message:
        raise ResolverError("no DoH upstream answered")

    sent: list[bytes] = []

    class Transport:
        def sendto(self, data: bytes, _addr: object) -> None:
            sent.append(data)

    protocol = ResolverProtocol(Resolver(RuleIndex(), broken, Nft()))
    protocol.transport = Transport()  # type: ignore[assignment]
    query = dns.message.make_query("example.org", "A")
    asyncio.run(protocol._answer(query.to_wire(), ("127.0.0.1", 5353)))
    assert dns.message.from_wire(sent[0]).rcode() == dns.rcode.SERVFAIL


def test_aaaa_of_a_tunnel_rule_is_empty_and_the_upstream_is_not_asked() -> None:
    upstream = Upstream(("www.netflix.com.", 300, "AAAA", "2001:db8::1"))
    resolver = Resolver(RuleIndex.from_config(smart_box()), upstream, Nft())
    response = resolver.resolve(dns.message.make_query("www.netflix.com", "AAAA"))
    assert response.answer == [] and upstream.asked == []
    direct = resolver.resolve(dns.message.make_query("bank.example", "AAAA"))
    assert direct.answer and upstream.asked == ["bank.example."]


def test_reload_keeps_what_was_learned_for_sites_still_under_a_rule() -> None:
    config = smart_box()
    resolver = Resolver(RuleIndex.from_config(config), Upstream(), Nft())
    assert resolver.learn("strm.yandex.net", "kinopoisk.ru")
    assert resolver.learn("nflx-cdn.example", "netflix.com")
    raw = config.model_dump(mode="json", exclude_none=True, exclude={"firewall"})
    raw["routing"]["domains"] = [
        rule for rule in raw["routing"]["domains"] if rule["domain"] != "netflix.com"
    ]
    resolver.reload(Config.model_validate(raw))
    assert resolver.index.match("strm.yandex.net") == "smart_dpn_de"
    assert resolver.index.match("nflx-cdn.example") is None
    assert resolver.learned == {"strm.yandex.net": "kinopoisk.ru"}
