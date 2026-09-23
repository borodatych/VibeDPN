"""Core's own words: the English base in code, the language of the box from the panel's file, and
the gate that keeps the shipped translation of core's keys whole."""

import json
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from vibedpn.engine.i18n import (
    BASE,
    KEY_PREFIX,
    Phrase,
    base_catalog,
    fill,
    load_catalog,
    placeholders,
)

REPO_ROOT = Path(__file__).resolve().parents[2]  # tests/ -> core/ -> repository root
LOCALES = REPO_ROOT / "ui" / "locales"
SHIPPED = sorted(LOCALES.glob("*.json"))
UTC = ZoneInfo("UTC")
MOMENT = 1_790_000_000.0  # 2026-09-21 14:13:20 UTC


def core_keys(path: Path) -> dict[str, str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {key: value for key, value in raw.items() if key.startswith(KEY_PREFIX)}


def test_every_phrase_has_its_english_string() -> None:
    assert set(BASE) == set(Phrase)
    assert all(phrase.value.startswith(KEY_PREFIX) for phrase in Phrase)


@pytest.mark.parametrize("path", SHIPPED, ids=lambda path: path.name)
def test_a_shipped_language_translates_every_key_of_core_and_no_other(path: Path) -> None:
    """The gate of core's keys: none missing, none dead, the same placeholders in each."""
    translated = core_keys(path)
    assert sorted(translated) == sorted(phrase.value for phrase in Phrase)
    for phrase in Phrase:
        assert (phrase.value, placeholders(translated[phrase.value])) == (
            phrase.value,
            placeholders(BASE[phrase]),
        )


def test_the_file_of_the_box_lays_its_strings_of_core_over_the_base(tmp_path: Path) -> None:
    (tmp_path / "de.json").write_text(
        json.dumps(
            {
                "bot.test": "Eine Testnachricht.",
                "bot.linked": 7,  # not a string: ignored
                "nav.status": "Status",  # the panel's: not core's to take
                "bot.no.such.key": "x",
            }
        ),
        encoding="utf-8",
    )
    catalog = load_catalog(tmp_path, "de")
    assert catalog.text(Phrase.TEST) == "Eine Testnachricht."
    assert catalog.text(Phrase.LINKED) == BASE[Phrase.LINKED]
    assert "nav.status" not in catalog.strings and "bot.no.such.key" not in catalog.strings


def test_a_missing_or_broken_file_leaves_english(tmp_path: Path) -> None:
    assert load_catalog(tmp_path, "fr").text(Phrase.TEST) == BASE[Phrase.TEST]
    (tmp_path / "uk.json").write_text("{ not json", encoding="utf-8")
    assert load_catalog(tmp_path, "uk").text(Phrase.TEST) == BASE[Phrase.TEST]
    assert load_catalog(tmp_path, "en").text(Phrase.TEST) == BASE[Phrase.TEST]


def test_placeholders_are_filled_by_name_and_a_missing_one_stays_visible() -> None:
    assert fill("{a} and {b}", {"a": 1}) == "1 and {b}"
    assert placeholders("{to} from {from}, {to}") == ["from", "to"]


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (0, "0 s"),
        (42, "42 s"),
        (60, "1 min"),
        (200, "3 min 20 s"),
        (3600, "1 h"),
        (3 * 3600 + 5 * 60 + 9, "3 h 5 min"),
        (2 * 86400 + 4 * 3600 + 59, "2 d 4 h"),
    ],
)
def test_a_duration_shows_its_two_largest_units(seconds: int, text: str) -> None:
    assert base_catalog().duration(seconds) == text


@pytest.mark.parametrize(
    ("amount", "text"),
    [
        (512, "512 B"),
        (1536, "1.5 KB"),
        (350 * 1024**2, "350 MB"),
        (int(1.25 * 1024**3), "1.2 GB"),
        (3 * 1024**5, "3072 TB"),
    ],
)
def test_a_size_is_in_the_largest_unit_below_1024_of_it(amount: int, text: str) -> None:
    assert base_catalog().size(amount) == text


def test_numbers_and_dates_take_the_forms_of_the_language() -> None:
    russian = load_catalog(LOCALES, "ru")
    assert russian.decimal(Decimal("1.23456"), 4) == "1,2345"
    assert russian.decimal(Decimal("2.5000"), 4) == "2,5"
    assert russian.decimal(Decimal(3), 4) == "3"
    assert russian.size(int(1.25 * 1024**3)) == "1,2 ГБ"
    assert russian.date(MOMENT, UTC) == "21.09.2026"
    assert base_catalog().date(MOMENT, UTC) == "2026-09-21"
    # the time of day alone today, with the date on another day
    assert base_catalog().time(MOMENT, UTC, MOMENT + 60) == "14:13"
    assert base_catalog().time(MOMENT, UTC, MOMENT + 86400) == "2026-09-21 14:13"
    assert russian.time(MOMENT, ZoneInfo("Europe/Moscow"), MOMENT + 86400) == "21.09.2026 17:13"
