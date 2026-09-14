"""Autolearning: a CDN asked right after its site by the same device follows the site;
generic names seen after many sites, other devices and old parents do not."""

from vibedpn.engine.learning import DnsEvent, Learned, Learner, Unlearned

RULES = {"kinopoisk.ru": True, "netflix.com": True, "bank.example": False}


def rule_of(name: str) -> tuple[str, bool] | None:
    labels = name.split(".")
    for start in range(len(labels) - 1):
        suffix = ".".join(labels[start:])
        if suffix in RULES:
            return suffix, RULES[suffix]
    return None


def ev(client: str, name: str, time: float) -> DnsEvent:
    return DnsEvent(client, name, time)


def test_a_cdn_right_after_its_site_on_the_same_device_is_learned() -> None:
    learner = Learner(rule_of)
    found = learner.observe_all(
        [ev("10.0.0.2", "www.kinopoisk.ru", 100.0), ev("10.0.0.2", "strm.yandex.net.", 102.5)]
    )
    assert found == [Learned("strm.yandex.net", "kinopoisk.ru")]
    assert learner.observe(ev("10.0.0.2", "strm.yandex.net", 103.0)) == []  # once is enough


def test_another_device_or_a_late_query_teaches_nothing() -> None:
    learner = Learner(rule_of)
    assert (
        learner.observe_all(
            [
                ev("10.0.0.2", "kinopoisk.ru", 100.0),
                ev("10.0.0.3", "strm.yandex.net", 101.0),
                ev("10.0.0.2", "late-cdn.example", 111.0),
            ]
        )
        == []
    )


def test_a_rule_without_learning_is_no_parent() -> None:
    learner = Learner(rule_of)
    assert (
        learner.observe_all([ev("c", "bank.example", 1.0), ev("c", "cdn.bank-cdn.example", 2.0)])
        == []
    )


def test_a_learned_name_seen_after_many_sites_is_unlearned_as_generic() -> None:
    learner = Learner(rule_of, generic_parents=1)
    first = learner.observe_all([ev("c", "a.kinopoisk.ru", 0.0), ev("c", "analytics.example", 1.0)])
    assert first == [Learned("analytics.example", "kinopoisk.ru")]
    second = learner.observe_all(
        [ev("c", "b.netflix.com", 50.0), ev("c", "analytics.example", 51.0)]
    )
    assert second == [Unlearned("analytics.example")]
    # generic stays generic: another site does not teach it again
    assert (
        learner.observe_all([ev("c", "kinopoisk.ru", 90.0), ev("c", "analytics.example", 91.0)])
        == []
    )
    learner.forget("analytics.example")  # the owner cleared it: fresh evidence may teach it again
    again = learner.observe_all(
        [ev("c", "kinopoisk.ru", 200.0), ev("c", "analytics.example", 201.0)]
    )
    assert again == [Learned("analytics.example", "kinopoisk.ru")]


def test_two_sites_open_at_once_leave_a_name_unassigned() -> None:
    learner = Learner(rule_of)
    found = learner.observe_all(
        [
            ev("c", "kinopoisk.ru", 0.0),
            ev("c", "netflix.com", 1.0),
            ev("c", "shared-cdn.example", 2.0),
        ]
    )
    assert found == []
