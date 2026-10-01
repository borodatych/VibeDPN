"""The last lines of a container's log, asked in the panel and read by the host (decision 38)

Only the host sees Docker, so core leaves a request with the service and the number of lines, and
the host answers with a report in core's data directory
The host takes only a service of this box (`docker compose config --services`): the name in the
request never reaches docker unchecked
Every line is cleaned of secrets before it leaves the host, the terminal included: a log pasted
into a chat or an issue must not carry a share link, a bot token or a key
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

# In core's data directory: the report of the last request, and the services of the box `up` saw
REPORT_FILE = "logs-report.json"
SERVICES_FILE = "services"
MAX_TAIL = 1000
# A Compose service name as this box writes them: `core`, `wg-client`, `wg-home2`, `myst-provider`
SERVICE_PATTERN = r"^[a-z0-9][a-z0-9-]{0,62}$"
_SERVICE = re.compile(SERVICE_PATTERN)
HIDDEN = "***"

# Order matters: a share link and a URL with a password go before the bare keys inside them
_SECRETS: tuple[tuple[re.Pattern[str], str], ...] = (
    # vless://<uuid>@host… — the UUID is the password of the person
    (re.compile(r"\b(vless|vmess|trojan|ss)://[^\s@/]+@", re.IGNORECASE), rf"\1://{HIDDEN}@"),
    # scheme://user:password@host
    (re.compile(r"://[^\s/:@]+:[^\s/@]+@"), f"://{HIDDEN}@"),
    # the Telegram Bot API token, in a URL (/bot<token>/) or bare
    (re.compile(r"(?<![0-9])\d{6,12}:[A-Za-z0-9_-]{30,}"), HIDDEN),
    # token=…, wpa_passphrase=…, private_key=… in a query or a line of settings
    (
        re.compile(
            r"\b(\w*(?:token|password|passphrase|secret|key|psk))=[^\s&\"']+", re.IGNORECASE
        ),
        rf"\1={HIDDEN}",
    ),
    # a UUID: the id of a person on the access server or of an xray uplink
    (
        re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I),
        HIDDEN,
    ),
    # WireGuard keys (base64 of 32 bytes) and REALITY keys (base64url of 32 bytes, unpadded)
    (re.compile(r"(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/]{42}[AEIMQUYcgkosw048]="), HIDDEN),
    (
        re.compile(r"(?<![A-Za-z0-9+/_=-])[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048](?![A-Za-z0-9_=-])"),
        HIDDEN,
    ),
)


class LogsError(ValueError):
    """A request the host does not answer: a bad name or a service this box does not run"""


@dataclass(frozen=True)
class LogsRequest:
    service: str
    tail: int


@dataclass(frozen=True)
class LogsReport:
    service: str
    tail: int
    finished_at: float
    text: str


def valid_service(name: str) -> bool:
    return _SERVICE.fullmatch(name) is not None


def request_word(service: str, tail: int) -> str:
    """The second line of the request core leaves: ``<service> <tail>``"""
    return f"{service} {tail}"


def parse_request(word: str, services: list[str]) -> LogsRequest:
    """The service and the number of lines asked, checked against the services of this box"""
    match word.split():
        case [service, count] if valid_service(service) and count.isdecimal():
            tail = int(count)
        case _:
            raise LogsError(f"not a request for a log: {word!r}")
    if service not in services:
        raise LogsError(f"this box runs no service {service}")
    if not 1 <= tail <= MAX_TAIL:
        raise LogsError(f"from 1 to {MAX_TAIL} lines, not {tail}")
    return LogsRequest(service, tail)


def parse_services(text: str) -> list[str]:
    """The output of `docker compose config --services`, or the services file: one per line"""
    return sorted({line.strip() for line in text.splitlines() if valid_service(line.strip())})


def redact(line: str) -> str:
    """``line`` with every secret this box can write into a log replaced by ``***``"""
    for pattern, replacement in _SECRETS:
        line = pattern.sub(replacement, line)
    return line


def report_text(report: LogsReport) -> str:
    return json.dumps(asdict(report), ensure_ascii=False) + "\n"
