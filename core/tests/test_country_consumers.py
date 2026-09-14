"""Consumers of the exit countries: the generated Compose file and their passphrases."""

import stat
from pathlib import Path
from typing import Any

from vibedpn.bootstrap import country_secrets, ensure_country_secrets, required_secrets
from vibedpn.compose import COUNTRIES_FILE, refresh_countries, render_countries
from vibedpn.config import Config

from .conftest import home_config


def countries_config(*countries: str) -> Config:
    raw: dict[str, Any] = home_config()
    raw["routing"]["domains"] = [
        {"domain": f"site{index}.example", "via": "dpn", "country": country}
        for index, country in enumerate(countries)
    ]
    return Config.model_validate(raw)


def test_each_country_extends_the_consumer_with_its_address_and_data() -> None:
    text = render_countries(countries_config("NL", "DE"))
    assert (
        "  myst-consumer-de:\n    extends:\n"
        "      file: compose.yaml\n      service: myst-consumer\n" in text
    )
    # DE sorts before NL, so it takes the first address
    assert "ipv4_address: 10.77.0.40" in text.split("myst-consumer-nl:")[0]
    assert "ipv4_address: 10.77.0.41" in text.split("myst-consumer-nl:")[1]
    assert "./data/myst-consumer-nl:/var/lib/mysterium-node" in text


def test_no_country_is_an_empty_file_that_still_exists(tmp_path: Path) -> None:
    config = Config.model_validate(home_config())
    assert render_countries(config).endswith("services: {}\n")
    assert refresh_countries(tmp_path, config) == tmp_path / COUNTRIES_FILE
    assert (tmp_path / COUNTRIES_FILE).is_file()


def test_a_new_country_gets_a_private_passphrase_once(tmp_path: Path) -> None:
    config = countries_config("DE")
    assert country_secrets(config) == ["myst-consumer-de-passphrase"]
    assert "myst-consumer-de-passphrase" in required_secrets(config)
    (created,) = ensure_country_secrets(tmp_path, config)
    assert stat.S_IMODE(created.stat().st_mode) == 0o600
    first = created.read_text(encoding="utf-8")
    assert ensure_country_secrets(tmp_path, config) == []
    assert created.read_text(encoding="utf-8") == first  # never replaced: it unlocks the identity
