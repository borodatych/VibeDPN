"""The Telegram Bot API as the box speaks it (decision 31, docs/manuals/telegramBot.md).

Every call is ``https://api.telegram.org/bot<token>/<method>`` with a JSON body, and every answer a
JSON object with ``ok`` and either ``result`` or ``description`` — with ``parameters.retry_after``
when Telegram wants a pause (https://core.telegram.org/bots/api). The token is part of every URL:
it lives in ``secrets/telegram.json`` with the chat the bot writes to, and a failure names its
class or Telegram's own description, never a URL.

The box reaches Telegram the way a device at home without a policy of its own does: the name is
resolved where AdGuard resolves it, and the exit is the one the chain ``steer`` of the router gives
that address (``router.exit_for``). The socket carries the mark of that exit before it connects:
httpx and httpcore set their socket options after ``connect``, and a mark set there would send the
handshake around the exit (knowledge telegram/botApi.md). IPv4 only: the exits are IPv4.
"""

from __future__ import annotations

import http.client
import json
import re
import socket
import ssl
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from ipaddress import AddressValueError, IPv4Address
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ValidationError

from vibedpn.atomic import write_private
from vibedpn.config import Config
from vibedpn.engine.resolver import Resolver, ResolverError, steerable
from vibedpn.engine.router import exit_for, uplink_table

SECRETS_FILE = "telegram.json"  # under secrets/: the token and the linked chat
API_URL = "https://api.telegram.org"
API_URL_ENV = "VIBEDPN_TELEGRAM_API"  # a test stand points core at its own Telegram
# What @BotFather hands out: the bot's id, a colon and the secret, "123456:ABC-DEF1234gh…"
# (https://core.telegram.org/bots/api#authorizing-your-bot). Nothing that could bend a URL.
TOKEN_PATTERN = re.compile(r"^\d+:[A-Za-z0-9_-]+$")
TIMEOUT_SECONDS = 20.0
MAX_ANSWER_BYTES = 1024 * 1024
DESCRIPTION_CHARS = 200
HTTPS_PORT = 443
HTTP_PORT = 80
# Linux names it in the socket module; elsewhere nothing can be marked, and nothing is steered.
SO_MARK: int | None = getattr(socket, "SO_MARK", None)
# Telegram's word for a token it does not know: 401 for a token of the right form, 404 for the rest
# (asked 2026-09-23 with a made-up token).
TOKEN_REJECTED = frozenset({401, 404})


class TelegramError(RuntimeError):
    """A call that did not work: the reason the owner reads, never the token."""

    def __init__(
        self, message: str, *, code: int | None = None, retry_after: float | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after

    @property
    def rejected(self) -> bool:
        """Telegram does not know the token: it was mistyped or revoked."""
        return self.code in TOKEN_REJECTED


class TelegramSecrets(BaseModel):
    """``secrets/telegram.json``: the token, the bot it belongs to, and the chat it writes to."""

    token: str
    bot: str = ""  # the bot's username, from getMe
    chat_id: int | None = None
    chat_name: str = ""  # how the linked chat names itself: @username or a first name
    linked_at: float | None = None


def check_token(text: str) -> str:
    token = text.strip()
    if TOKEN_PATTERN.fullmatch(token) is None:
        raise TelegramError("a bot token is the bot's number, a colon and letters: 123456:ABC-…")
    return token


def load_secrets(directory: Path) -> TelegramSecrets | None:
    try:
        return TelegramSecrets.model_validate_json((directory / SECRETS_FILE).read_text("utf-8"))
    except (OSError, ValueError, ValidationError):
        return None


def save_secrets(directory: Path, secrets: TelegramSecrets) -> None:
    write_private(directory / SECRETS_FILE, secrets.model_dump_json(indent=2) + "\n")


@dataclass(frozen=True)
class Endpoint:
    """Where the Bot API is: Telegram itself, or a test stand's stand-in."""

    tls: bool
    host: str
    port: int
    path: str  # a prefix of the stand-in's URL; "" for Telegram


def endpoint(url: str) -> Endpoint:
    parts = urlsplit(url)
    tls = parts.scheme == "https"
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise TelegramError(f"{url!r} is not an http(s) URL of a Bot API")
    return Endpoint(
        tls=tls,
        host=parts.hostname,
        port=parts.port or (HTTPS_PORT if tls else HTTP_PORT),
        path=parts.path.rstrip("/"),
    )


Rule = Callable[[str], str | None]  # a name → the channel set of the rule it falls under
Addresses = Callable[[str], list[str]]  # a name → its IPv4 addresses


@dataclass(frozen=True)
class Lookup:
    """How the bot finds Telegram's address and the rule over its name."""

    rule: Rule
    addresses: Addresses


def resolver_lookup(resolver: Resolver) -> Lookup:
    """A box with AdGuard: the resolver of smart asks the DoH upstreams and knows the rules — the
    live ones, with the lists and what it learned, so its index is read at every call."""

    def rule(name: str) -> str | None:
        return resolver.index.match(name)  # a reload replaces the index, never changes it in place

    return Lookup(rule=rule, addresses=resolver.lookup)


def _no_rule(_name: str) -> str | None:
    return None


def _system_addresses(name: str) -> list[str]:
    infos = socket.getaddrinfo(name, None, socket.AF_INET, socket.SOCK_STREAM)
    return steerable(dict.fromkeys(str(info[4][0]) for info in infos))


def system_lookup() -> Lookup:
    """A box without AdGuard: the system resolver, and no domain rules — without AdGuard nothing
    fills their sets, so a device at home is not steered by them either."""
    return Lookup(rule=_no_rule, addresses=_system_addresses)


@dataclass(frozen=True)
class Route:
    """How one call reaches Telegram: the address it connects to, and the exit with its mark."""

    address: str
    exit: str | None  # an uplink key; None: direct
    mark: int | None


def route_to(config: Config, where: Endpoint, lookup: Lookup) -> Route:
    """The address of the API and the exit a device at home would take to it."""
    literal = _literal(where.host)
    if literal is not None:
        address, rule = literal, None
    else:
        address, rule = _resolved(where.host, lookup), lookup.rule(where.host)
    key = exit_for(config, rule, IPv4Address(address))
    return Route(address, key, None if key is None else uplink_table(config)[key].mark)


def _literal(host: str) -> str | None:
    try:
        return str(IPv4Address(host))
    except AddressValueError:
        return None


def _resolved(host: str, lookup: Lookup) -> str:
    try:
        found = lookup.addresses(host)
    except (ResolverError, OSError) as exc:
        raise TelegramError(f"cannot resolve {host}: {exc}") from None
    if not found:
        raise TelegramError(f"{host} has no IPv4 address")
    return found[0]


DIRECT = "direct"  # no uplink key is spelled so: tor, dpn, vps, xray, dpn-<cc>, wg-<name>


def via(route: Route) -> str:
    """The exit of a route as data: its uplink key, or ``direct``; the reader words it."""
    return route.exit if route.exit is not None else DIRECT


def _marked_socket(route: Route, port: int, timeout: float | None) -> socket.socket:
    """A socket that carries the exit's mark from its first packet on."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if route.mark is not None:
            if SO_MARK is None:
                raise OSError("this system cannot mark a socket for an exit")
            sock.setsockopt(socket.SOL_SOCKET, SO_MARK, route.mark)
        sock.settimeout(timeout)
        sock.connect((route.address, port))
    except BaseException:
        sock.close()
        raise
    return sock


class _PlainConnection(http.client.HTTPConnection):
    """HTTP to a test stand, over the marked socket; the Host header stays the stand's name."""

    def __init__(self, where: Endpoint, route: Route, timeout: float) -> None:
        super().__init__(where.host, where.port, timeout=timeout)
        self._route = route

    def connect(self) -> None:
        self.sock = _marked_socket(self._route, self.port, self.timeout)


class _TlsConnection(http.client.HTTPSConnection):
    """HTTPS to the address the resolver gave, checked against the name: TLS sends the name as
    SNI and verifies the certificate for it, whatever address the socket went to."""

    def __init__(
        self, where: Endpoint, route: Route, timeout: float, context: ssl.SSLContext
    ) -> None:
        super().__init__(where.host, where.port, timeout=timeout, context=context)
        self._route = route
        self._tls = context

    def connect(self) -> None:
        sock = _marked_socket(self._route, self.port, self.timeout)
        self.sock = self._tls.wrap_socket(sock, server_hostname=self.host)


Transport = Callable[[Endpoint, Route, str, bytes, float], tuple[int, bytes]]


def marked_request(
    where: Endpoint, route: Route, target: str, body: bytes, timeout: float
) -> tuple[int, bytes]:
    """POST a JSON body and read the answer, over a socket marked for the route's exit."""
    connection: http.client.HTTPConnection = (
        _TlsConnection(where, route, timeout, ssl.create_default_context())
        if where.tls
        else _PlainConnection(where, route, timeout)
    )
    try:
        connection.request("POST", target, body=body, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        return response.status, response.read(MAX_ANSWER_BYTES + 1)
    finally:
        connection.close()


def call(
    where: Endpoint,
    route: Route,
    token: str,
    method: str,
    payload: Mapping[str, object],
    *,
    timeout: float = TIMEOUT_SECONDS,
    transport: Transport = marked_request,
) -> object:
    """One method of the Bot API; its ``result``, or ``TelegramError`` with Telegram's words."""
    target = f"{where.path}/bot{token}/{method}"
    try:
        status, raw = transport(where, route, target, json.dumps(payload).encode(), timeout)
    except (OSError, http.client.HTTPException) as exc:
        # the class only: an error's text may quote the request, and the request is the token
        raise TelegramError(f"{where.host} ({via(route)}): {exc.__class__.__name__}") from None
    return _answer(status, raw)


def _answer(status: int, raw: bytes) -> object:
    if len(raw) > MAX_ANSWER_BYTES:
        raise TelegramError(f"HTTP {status}: an answer longer than {MAX_ANSWER_BYTES} bytes")
    try:
        body: object = json.loads(raw)
    except ValueError:
        raise TelegramError(f"HTTP {status}: not an answer of the Bot API") from None
    if not isinstance(body, dict):
        raise TelegramError(f"HTTP {status}: not an answer of the Bot API")
    if body.get("ok") is True:
        return body.get("result")
    code = body.get("error_code")
    parameters = body.get("parameters")
    retry = parameters.get("retry_after") if isinstance(parameters, dict) else None
    description = str(body.get("description") or f"HTTP {status}")[:DESCRIPTION_CHARS]
    raise TelegramError(
        f"Telegram: {description}",
        code=code if isinstance(code, int) else status,
        retry_after=float(retry) if isinstance(retry, int | float) else None,
    )


START_COMMAND = "/start"
PRIVATE_CHAT = "private"


@dataclass(frozen=True)
class Update:
    """A message the bot received, as much of it as linking a chat needs."""

    id: int
    text: str
    chat_id: int | None
    chat_type: str
    chat_name: str


def parse_updates(result: object) -> list[Update]:
    """The updates of ``getUpdates``; anything that is not a message still moves the offset."""
    updates: list[Update] = []
    for item in result if isinstance(result, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("update_id"), int):
            continue
        message = item.get("message")
        message = message if isinstance(message, dict) else {}
        chat = message.get("chat")
        chat = chat if isinstance(chat, dict) else {}
        text = message.get("text")
        chat_id = chat.get("id")
        updates.append(
            Update(
                id=item["update_id"],
                text=text if isinstance(text, str) else "",
                chat_id=chat_id if isinstance(chat_id, int) else None,
                chat_type=str(chat.get("type") or ""),
                chat_name=_chat_name(chat),
            )
        )
    return updates


def _chat_name(chat: dict[str, object]) -> str:
    username = chat.get("username")
    if isinstance(username, str) and username:
        return f"@{username}"
    for field in ("first_name", "title"):
        value = chat.get(field)
        if isinstance(value, str) and value:
            return value
    return str(chat.get("id") or "")


def start_code(text: str) -> str | None:
    """The code a deep link carried: ``https://t.me/<bot>?start=<code>`` makes the app send
    ``/start <code>`` (https://core.telegram.org/bots/features#deep-linking)."""
    command, _space, code = text.strip().partition(" ")
    if command != START_COMMAND:
        return None
    return code.strip() or None
