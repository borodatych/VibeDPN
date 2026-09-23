"""A DNS name that follows the changing public address of the box (``ddns`` in config.yaml).

The owner's DDNS service hands out an update URL with a token in it: it lives in
``secrets/ddns-url`` and never in config.yaml, a log or an answer of the API. core learns the public
address the way ``vibedpn doctor --network`` does and calls the URL only when that address changed,
and once a day besides, so a service that expires quiet names keeps this one. Blind calls every few
minutes are what No-IP blocks clients for: "Excessive nochg responses may result in your client
being blocked" (https://www.noip.com/integrate/response).

Services answer in their own words, and some say "failed" with HTTP 200: DuckDNS answers ``KO``
(https://www.duckdns.org/spec.jsp), the dyndns2 family ``badauth``, ``nohost`` and the like (the
No-IP page above). A call succeeds on a 2xx whose first word is none of those.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from collections.abc import Awaitable, Callable
from ipaddress import AddressValueError, IPv4Address
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ValidationError

from vibedpn.atomic import write_private
from vibedpn.config import Config

URL_FILE = "ddns-url"  # under secrets/
STATE_FILE = "ddns.json"  # in core's data directory: what the service was last told, and when
# The public address comes from the same place `doctor --network` asks; the service logs nothing
# (https://www.ipify.org/). The environment variable points a test stand at its own echo server.
PUBLIC_IP_URL = "https://api.ipify.org"
PUBLIC_IP_URL_ENV = "VIBEDPN_EXIT_IP_URL"
INTERVAL_SECONDS = 300
REFRESH_SECONDS = 24 * 3600
TIMEOUT_SECONDS = 20
# Put where the address goes, for a service that wants it in the URL; most take the caller's.
IP_PLACEHOLDER = "{ip}"
FAILURE_WORDS = frozenset(
    {"ko", "badauth", "badagent", "nohost", "notfqdn", "numhost", "abuse", "dnserr", "911"}
)
ANSWER_CHARS = 80
# https only: the token travels in the URL
URL_PATTERN = re.compile(r"^https://[^\s/]+/\S*$")

Sleep = Callable[[float], Awaitable[None]]
Now = Callable[[], float]


class DdnsError(ValueError):
    """An update URL this box will not keep, with the reason the owner reads."""


class DdnsState(BaseModel):
    """What the watcher knows; ``told_*`` is what the service accepted last."""

    public_ip: str | None = None
    told_ip: str | None = None
    told_at: float | None = None
    last_ok: bool | None = None
    last_at: float | None = None
    message: str = ""


def check_url(url: str) -> str:
    text = url.strip()
    if URL_PATTERN.fullmatch(text) is None:
        raise DdnsError("the update URL must be one https:// address without spaces")
    return text


def host_of(url: str) -> str:
    """What the owner may see of the URL: the service, never the token."""
    return urlsplit(url).hostname or ""


def load_url(secrets_dir: Path) -> str | None:
    try:
        return check_url((secrets_dir / URL_FILE).read_text(encoding="utf-8"))
    except (OSError, DdnsError):
        return None


def save_url(secrets_dir: Path, url: str) -> str:
    text = check_url(url)
    write_private(secrets_dir / URL_FILE, text + "\n")
    return text


def load_state(path: Path) -> DdnsState:
    try:
        return DdnsState.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError):
        return DdnsState()


def save_state(path: Path, state: DdnsState) -> None:
    write_private(path, state.model_dump_json(indent=2) + "\n")


def judge(status: int, body: str) -> tuple[bool, str]:
    """Did the service take it, and its first line to show — some fail with HTTP 200."""
    text = body.strip()
    first_line = text.splitlines()[0][:ANSWER_CHARS] if text else ""
    first_word = text.split(maxsplit=1)[0].lower() if text else ""
    ok = httpx.codes.is_success(status) and first_word not in FAILURE_WORDS
    return ok, f"{status} {first_line}".strip()


def due(state: DdnsState, public_ip: str, now: float) -> bool:
    if state.told_ip != public_ip or state.told_at is None:
        return True
    return now - state.told_at >= REFRESH_SECONDS


def public_ip(client: httpx.Client) -> str:
    response = client.get(os.environ.get(PUBLIC_IP_URL_ENV, PUBLIC_IP_URL))
    response.raise_for_status()
    try:
        return str(IPv4Address(response.text.strip()))
    except AddressValueError:
        raise DdnsError(f"the public address service answered {response.text[:40]!r}") from None


def ddns_round(
    config: Config, secrets_dir: Path, state_path: Path, client: httpx.Client, now: float
) -> DdnsState | None:
    """One look at the public address and, when it moved, one call of the update URL. ``None``
    while ddns is off. Messages never carry the URL: only its host."""
    if not config.ddns.enabled:
        return None
    state = load_state(state_path)
    url = load_url(secrets_dir)
    if url is None:
        state = state.model_copy(
            update={"last_ok": False, "last_at": now, "message": "no update URL: vibedpn ddns set"}
        )
        save_state(state_path, state)
        return state
    try:
        address = public_ip(client)
    except (httpx.HTTPError, DdnsError) as exc:
        state = state.model_copy(
            update={"last_ok": False, "last_at": now, "message": f"no public address: {exc}"}
        )
        save_state(state_path, state)
        return state
    state = state.model_copy(update={"public_ip": address})
    if due(state, address, now):
        state = _tell(state, url, address, client, now)
    save_state(state_path, state)
    return state


def _tell(state: DdnsState, url: str, address: str, client: httpx.Client, now: float) -> DdnsState:
    try:
        response = client.get(url.replace(IP_PLACEHOLDER, address))
    except httpx.HTTPError as exc:
        # the class of the failure only: an error's text may quote the URL, and the URL is the token
        return state.model_copy(
            update={
                "last_ok": False,
                "last_at": now,
                "message": f"{host_of(url)}: {exc.__class__.__name__}",
            }
        )
    ok, answer = judge(response.status_code, response.text)
    update: dict[str, object] = {"last_ok": ok, "last_at": now, "message": answer}
    if ok:
        update |= {"told_ip": address, "told_at": now}
    return state.model_copy(update=update)


async def watch_ddns(
    current: Callable[[], Config],
    secrets_dir: Path,
    state_path: Path,
    *,
    client: httpx.Client | None = None,
    sleep: Sleep = asyncio.sleep,
    now: Now = time.time,
    rounds: int | None = None,
) -> None:
    """A round every ``INTERVAL_SECONDS`` while core runs; ``rounds`` bounds it for the tests. It
    reads the live configuration, so turning ddns off stops the calls without a restart."""
    http = client or httpx.Client(timeout=TIMEOUT_SECONDS, trust_env=False)
    round_number = 0
    try:
        while rounds is None or round_number < rounds:
            round_number += 1
            try:
                state = await asyncio.to_thread(
                    ddns_round, current(), secrets_dir, state_path, http, now()
                )
                if state is not None and state.last_ok is False:
                    sys.stderr.write(f"vibedpn-core: ddns: {state.message}\n")
            except OSError as exc:
                sys.stderr.write(f"vibedpn-core: ddns: cannot keep its state: {exc.strerror}\n")
            await sleep(INTERVAL_SECONDS)
    finally:
        if client is None:
            http.close()
