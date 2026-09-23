"""Core's own words: what core says to the owner by itself, the messages of the Telegram bot.

English is the base and lives here, in code, so core talks with an empty, missing or broken folder
of languages. Every other language is the file the panel reads, ``data/ui/locales/<code>.json`` of
the box (docs/manuals/languageFileSpec.md): core takes from it the keys under ``bot.`` and nothing
else, laid over the base, so half a translation is already of use. A placeholder without a value
stays visible. Nothing in core branches on the text of a string: a notice is data, and its phrase
is built here, with the numbers, sizes and dates in the forms the language file gives.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, tzinfo
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum
from pathlib import Path

LOCALES_DIR = Path("data/ui/locales")  # under the box directory, shared with the panel
BASE_LANGUAGE = "en"
KEY_PREFIX = "bot."  # the keys of a language file that are core's; the panel's gate leaves them
PLACEHOLDER = re.compile(r"\{(\w+)\}")
BYTES_PER_UNIT = 1024
ONE_DECIMAL_BELOW = 10  # 1.2 GB, but 12 GB: a tenth of a large amount says nothing
SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 24 * 3600


class Phrase(StrEnum):
    UPLINK_DOWN = "bot.uplink.down"
    UPLINK_BACK = "bot.uplink.back"
    UPLINK_OUTAGE = "bot.uplink.outage"
    WIFI_DOWN = "bot.wifi.down"
    WIFI_BACK = "bot.wifi.back"
    WIFI_OUTAGE = "bot.wifi.outage"
    DDNS_DOWN = "bot.ddns.down"
    DDNS_BACK = "bot.ddns.back"
    DDNS_OUTAGE = "bot.ddns.outage"
    ADDRESS_CHANGED = "bot.address.changed"
    BOX_BACK = "bot.box.back"
    APPLY_FAILED = "bot.apply.failed"
    TEST = "bot.test"
    LINKED = "bot.linked"
    REPORT_TITLE = "bot.report.title"
    REPORT_NODE_EARNED = "bot.report.node.earned"
    REPORT_NODE_TOTAL = "bot.report.node.total"
    REPORT_NODE_OFF = "bot.report.node.off"
    REPORT_NODE_SILENT = "bot.report.node.silent"
    REPORT_EXITS_FINE = "bot.report.exits.fine"
    REPORT_EXITS_DOWN = "bot.report.exits.down"
    REPORT_EXIT = "bot.report.exit"
    REPORT_PEOPLE_NONE = "bot.report.people.none"
    REPORT_PEOPLE_USED = "bot.report.people.used"
    REPORT_PERSON = "bot.report.person"
    REPORT_ADDRESS_CHANGES = "bot.report.address.changes"
    UNIT_SECONDS = "bot.unit.seconds"
    UNIT_MINUTES = "bot.unit.minutes"
    UNIT_HOURS = "bot.unit.hours"
    UNIT_DAYS = "bot.unit.days"
    UNIT_BYTES = "bot.unit.bytes"
    UNIT_KILOBYTES = "bot.unit.kilobytes"
    UNIT_MEGABYTES = "bot.unit.megabytes"
    UNIT_GIGABYTES = "bot.unit.gigabytes"
    UNIT_TERABYTES = "bot.unit.terabytes"
    FORMAT_DECIMAL = "bot.format.decimal"
    FORMAT_TIME = "bot.format.time"
    FORMAT_DATE = "bot.format.date"
    FORMAT_DATETIME = "bot.format.datetime"


BASE: dict[Phrase, str] = {
    Phrase.UPLINK_DOWN: "Exit {name} has not answered since {time}.",
    Phrase.UPLINK_BACK: "Exit {name} answers again after {duration} of silence.",
    Phrase.UPLINK_OUTAGE: "Exit {name} was silent for {duration}, {from} to {to}.",
    Phrase.WIFI_DOWN: "The Wi-Fi access point {name} has been off since {time}.",
    Phrase.WIFI_BACK: "The Wi-Fi access point {name} is on again after {duration}.",
    Phrase.WIFI_OUTAGE: "The Wi-Fi access point {name} was off for {duration}, {from} to {to}.",
    Phrase.DDNS_DOWN: "The DNS name of the box has not followed its address since {time}: {reason}",
    Phrase.DDNS_BACK: "The DNS name of the box follows its address again after {duration}.",
    Phrase.DDNS_OUTAGE: (
        "The DNS name of the box did not follow its address for {duration}, {from} to {to}:"
        " {reason}"
    ),
    Phrase.ADDRESS_CHANGED: "The public address of the box changed: {old} → {new}.",
    Phrase.BOX_BACK: "The box is back: it was off for {duration}, {from} to {to}.",
    Phrase.APPLY_FAILED: "A change made in the panel was not applied: {reason}",
    Phrase.TEST: "A test message from your VibeDPN box.",
    Phrase.LINKED: "This chat now gets the alerts and the weekly report of your VibeDPN box.",
    Phrase.REPORT_TITLE: "VibeDPN weekly report, {from} to {to}",
    Phrase.REPORT_NODE_EARNED: "Node: {earned} MYST earned in these days, {total} MYST in all.",
    Phrase.REPORT_NODE_TOTAL: "Node: {total} MYST earned in all.",
    Phrase.REPORT_NODE_OFF: "Node: off.",
    Phrase.REPORT_NODE_SILENT: "Node: did not answer.",
    Phrase.REPORT_EXITS_FINE: "Exits: no outages.",
    Phrase.REPORT_EXITS_DOWN: "Exits were silent: {list}.",
    Phrase.REPORT_EXIT: "{name} {duration}",
    Phrase.REPORT_PEOPLE_NONE: "Access server: nobody used it.",
    Phrase.REPORT_PEOPLE_USED: "Access server: {list}.",
    Phrase.REPORT_PERSON: "{name} {amount}",
    Phrase.REPORT_ADDRESS_CHANGES: "Changes of the public address: {count}.",
    Phrase.UNIT_SECONDS: "{count} s",
    Phrase.UNIT_MINUTES: "{count} min",
    Phrase.UNIT_HOURS: "{count} h",
    Phrase.UNIT_DAYS: "{count} d",
    Phrase.UNIT_BYTES: "{count} B",
    Phrase.UNIT_KILOBYTES: "{count} KB",
    Phrase.UNIT_MEGABYTES: "{count} MB",
    Phrase.UNIT_GIGABYTES: "{count} GB",
    Phrase.UNIT_TERABYTES: "{count} TB",
    Phrase.FORMAT_DECIMAL: "{whole}.{fraction}",
    Phrase.FORMAT_TIME: "{hour}:{minute}",
    Phrase.FORMAT_DATE: "{year}-{month}-{day}",
    Phrase.FORMAT_DATETIME: "{date} {time}",
}
SIZE_UNITS = (
    Phrase.UNIT_KILOBYTES,
    Phrase.UNIT_MEGABYTES,
    Phrase.UNIT_GIGABYTES,
    Phrase.UNIT_TERABYTES,
)


def fill(template: str, params: Mapping[str, str | int]) -> str:
    """A template with its placeholders filled by name; one without a value stays visible."""
    return PLACEHOLDER.sub(
        lambda match: str(params[match[1]]) if match[1] in params else match[0], template
    )


def placeholders(text: str) -> list[str]:
    """The placeholder names of a string, sorted: a translation keeps the same set."""
    return sorted({match[1] for match in PLACEHOLDER.finditer(text)})


@dataclass(frozen=True)
class Catalog:
    """The strings of one language over the English base, and the forms of its numbers."""

    strings: Mapping[str, str]

    def text(self, phrase: Phrase, **params: str | int) -> str:
        return fill(self.strings.get(phrase.value, BASE[phrase]), params)

    def decimal(self, value: Decimal, places: int) -> str:
        """``value`` cut to ``places`` decimals, without trailing zeros."""
        cut = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_DOWN)
        whole, _dot, fraction = f"{cut:f}".partition(".")
        fraction = fraction.rstrip("0")
        return (
            self.text(Phrase.FORMAT_DECIMAL, whole=whole, fraction=fraction) if fraction else whole
        )

    def duration(self, seconds: float) -> str:
        """The two largest units that matter: 1 h 5 min, 3 min 20 s, 2 d 4 h."""
        total = max(0, int(seconds))
        days, rest = divmod(total, SECONDS_PER_DAY)
        hours, rest = divmod(rest, SECONDS_PER_HOUR)
        minutes, secs = divmod(rest, SECONDS_PER_MINUTE)
        if days:
            parts = [(Phrase.UNIT_DAYS, days), (Phrase.UNIT_HOURS, hours)]
        elif hours:
            parts = [(Phrase.UNIT_HOURS, hours), (Phrase.UNIT_MINUTES, minutes)]
        elif minutes:
            parts = [(Phrase.UNIT_MINUTES, minutes), (Phrase.UNIT_SECONDS, secs)]
        else:
            parts = [(Phrase.UNIT_SECONDS, secs)]
        first, *rest_parts = parts
        shown = [first, *[(unit, count) for unit, count in rest_parts if count]]
        return " ".join(self.text(unit, count=count) for unit, count in shown)

    def size(self, amount: int) -> str:
        """Bytes in the largest unit below 1024 of it: 350 MB, 1.2 GB."""
        if amount < BYTES_PER_UNIT:
            return self.text(Phrase.UNIT_BYTES, count=max(0, amount))
        value = Decimal(amount) / BYTES_PER_UNIT
        index = 0
        while value >= BYTES_PER_UNIT and index < len(SIZE_UNITS) - 1:
            value /= BYTES_PER_UNIT
            index += 1
        places = 1 if value < ONE_DECIMAL_BELOW else 0
        return self.text(SIZE_UNITS[index], count=self.decimal(value, places))

    def date(self, moment: float, zone: tzinfo) -> str:
        local = datetime.fromtimestamp(moment, zone)
        return self.text(
            Phrase.FORMAT_DATE,
            year=f"{local.year:04d}",
            month=f"{local.month:02d}",
            day=f"{local.day:02d}",
        )

    def time(self, moment: float, zone: tzinfo, now: float) -> str:
        """The time of day, with the date in front when it is not today."""
        local = datetime.fromtimestamp(moment, zone)
        clock = self.text(
            Phrase.FORMAT_TIME, hour=f"{local.hour:02d}", minute=f"{local.minute:02d}"
        )
        if local.date() == datetime.fromtimestamp(now, zone).date():
            return clock
        return self.text(Phrase.FORMAT_DATETIME, date=self.date(moment, zone), time=clock)


def base_catalog() -> Catalog:
    return Catalog({phrase.value: text for phrase, text in BASE.items()})


def load_catalog(directory: Path, language: str) -> Catalog:
    """The language of the box, read once: a missing file leaves English, a broken one too, with a
    line in the log. Only string values of core's keys are taken."""
    strings = {phrase.value: text for phrase, text in BASE.items()}
    if language == BASE_LANGUAGE:
        return Catalog(strings)
    path = directory / f"{language}.json"
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Catalog(strings)
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"vibedpn-core: cannot read language file {path}: {exc}; English\n")
        return Catalog(strings)
    if isinstance(raw, dict):
        strings.update(
            {key: value for key, value in raw.items() if key in strings and isinstance(value, str)}
        )
    return Catalog(strings)
