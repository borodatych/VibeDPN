"""Exit countries of domain rules: sorted, numbered, limited."""

from typing import Any

import pytest
from pydantic import ValidationError

from vibedpn.config import MAX_RULE_COUNTRIES, Config
from vibedpn.engine.router import MAX_COUNTRIES, Uplink, country_uplinks, rule_countries

from .conftest import home_config


def with_rules(*rules: dict[str, Any]) -> dict[str, Any]:
    raw = home_config()
    raw["routing"]["domains"] = list(rules)
    return raw


def test_countries_are_sorted_unique_and_numbered() -> None:
    config = Config.model_validate(
        with_rules(
            {"domain": "kinopoisk.ru", "via": "dpn", "country": "nl"},
            {"domain": "bbc.co.uk", "via": "dpn", "country": "GB"},
            {"domain": "zdf.de", "via": "dpn", "country": "NL"},
            {"domain": "any.example", "via": "dpn"},
            {"domain": "bank.example", "via": "direct"},
        )
    )
    assert rule_countries(config) == ["GB", "NL"]
    assert country_uplinks(config) == {
        "GB": Uplink(mark=0x40, table=7740, gateway="10.77.0.40"),
        "NL": Uplink(mark=0x41, table=7741, gateway="10.77.0.41"),
    }


def test_at_most_eight_countries() -> None:
    assert MAX_RULE_COUNTRIES == MAX_COUNTRIES
    codes = ["AT", "BE", "CH", "DE", "ES", "FR", "GB", "IT", "NL"]
    rules = [
        {"domain": f"s{index}.example", "via": "dpn", "country": code}
        for index, code in enumerate(codes)
    ]
    with pytest.raises(ValidationError, match="9 exit countries, at most 8"):
        Config.model_validate(with_rules(*rules))
    Config.model_validate(with_rules(*rules[:8]))
