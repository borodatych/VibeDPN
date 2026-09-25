"""Ready lists of routing.lists (docs/decisions.md, 21): parse, cache, fetch.

A list is a text file by URL. Three line forms are read, because the lists people publish come in
them: a bare domain, a hosts-file line (``0.0.0.0 example.org``) and the domain form of adblock
rules (``||example.org^``). Anything else — paths, wildcards, regular expressions, exceptions — is
skipped: a channel is chosen per domain, and a guess at a pattern would route the wrong sites.

A line that is an IPv4 network, ``a.b.c.d/nn``, is a network of the list (antifilter publishes lists
of networks this way): the addresses in it take the channel of the list, as routing.networks does
The slash is required: a bare address alone on a line is no network anyone meant
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from ipaddress import IPv4Network, ip_address
from pathlib import Path

import httpx

from vibedpn.config import normalize_domain

LISTS_DIR = "lists"  # under data/core
LIST_REFRESH_SECONDS = 24 * 3600.0
LIST_TIMEOUT_SECONDS = 30.0
MAX_LIST_BYTES = 16 * 1024 * 1024
MAX_LIST_DOMAINS = 500_000
MAX_LIST_NETWORKS = 100_000
NETWORK_MARK = "/"
CACHE_NAME_CHARS = 16  # of the sha256 of the URL
HTTP_OK = 200
COMMENT_MARKS = ("#", "!")
ADBLOCK_PREFIX = "||"
ADBLOCK_END = "^"
# Names hosts files carry for the machine itself, never a site.
HOST_NAMES = frozenset({"localhost.localdomain", "ip6-localhost.localdomain"})

Fetch = Callable[[str], str]


class ListError(RuntimeError):
    """A user-facing reason why a list could not be fetched or read."""


def _is_address(token: str) -> bool:
    try:
        ip_address(token)
    except ValueError:
        return False
    return True


def _line_names(line: str) -> list[str]:
    if line.startswith(ADBLOCK_PREFIX):
        rule = line.removeprefix(ADBLOCK_PREFIX)
        # `||example.org^` only: a path, a wildcard or options narrow the rule to part of a site
        return [rule.removesuffix(ADBLOCK_END)] if rule.endswith(ADBLOCK_END) else []
    tokens = line.split()
    if len(tokens) > 1 and _is_address(tokens[0]):
        return tokens[1:]
    # an address alone on a line is no name: normalize_domain would take it for one
    return tokens if len(tokens) == 1 and not _is_address(tokens[0]) else []


@dataclass(frozen=True)
class ListContent:
    """What one list names: its domains in their order and its networks, each once"""

    domains: list[str]
    networks: list[IPv4Network]

    def empty(self) -> bool:
        return not self.domains and not self.networks


def _line_network(line: str) -> IPv4Network | None:
    if NETWORK_MARK not in line or " " in line:
        return None
    try:
        # strict=False: a list that writes 10.1.2.3/24 means the network 10.1.2.0/24
        return IPv4Network(line, strict=False)
    except ValueError:
        return None


def parse_list(text: str) -> ListContent:
    """The domains and the networks of a list; lines that are neither are skipped."""
    found: dict[str, None] = {}
    networks: dict[IPv4Network, None] = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(COMMENT_MARKS):
            continue
        network = _line_network(line)
        if network is not None:
            if len(networks) < MAX_LIST_NETWORKS:
                networks[network] = None
            continue
        if len(found) >= MAX_LIST_DOMAINS:
            continue
        for name in _line_names(line):
            try:
                domain = normalize_domain(name)
            except ValueError:
                continue
            if domain not in HOST_NAMES and len(found) < MAX_LIST_DOMAINS:
                found[domain] = None
    return ListContent(list(found), list(networks))


class ListCache:
    """The last good copy of every list, one file per URL; a list works from it while its URL is
    down, and after a restart without the network."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:CACHE_NAME_CHARS]
        return self.directory / f"{digest}.txt"

    def load(self, url: str) -> tuple[str, float] | None:
        """The copy and when it was fetched (unix seconds), or ``None`` without one."""
        path = self.path(url)
        try:
            return path.read_text(encoding="utf-8"), path.stat().st_mtime
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise ListError(f"cannot read the copy {path}: {exc.strerror or exc}") from exc

    def save(self, url: str, text: str) -> None:
        path = self.path(url)
        temporary = path.with_suffix(".tmp")
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary.write_text(text, encoding="utf-8")
            temporary.replace(path)
        except OSError as exc:
            raise ListError(f"cannot write the copy {path}: {exc.strerror or exc}") from exc

    def prune(self, urls: Iterable[str]) -> None:
        """Remove the copies of lists config.yaml no longer has."""
        kept = {self.path(url).name for url in urls}
        if not self.directory.is_dir():
            return
        for path in self.directory.glob("*.txt"):
            if path.name not in kept:
                path.unlink(missing_ok=True)


def http_fetch(client: httpx.Client) -> Fetch:
    """GET a list; a status other than 200 or a body above MAX_LIST_BYTES is a ListError."""

    def fetch(url: str) -> str:
        chunks: list[bytes] = []
        size = 0
        try:
            with client.stream("GET", url, follow_redirects=True) as response:
                if response.status_code != HTTP_OK:
                    raise ListError(f"{url}: HTTP {response.status_code}")
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_LIST_BYTES:
                        raise ListError(f"{url}: larger than {MAX_LIST_BYTES // 1024 // 1024} MiB")
                    chunks.append(chunk)
        except httpx.HTTPError as exc:
            raise ListError(f"{url}: {type(exc).__name__}: {exc}") from exc
        return b"".join(chunks).decode("utf-8", errors="replace")

    return fetch


def list_client() -> httpx.Client:
    # trust_env=False: a proxy of the environment would decide which way a list is fetched
    return httpx.Client(timeout=LIST_TIMEOUT_SECONDS, trust_env=False)


@dataclass(frozen=True)
class ListState:
    """What core has of one list: how many domains and networks, from when, why it is not newer."""

    url: str
    domains: int
    fetched_at: float | None  # unix seconds of the copy in use; None: no copy at all
    error: str = ""
    networks: int = 0


def refresh_list(
    url: str,
    cache: ListCache,
    fetch: Fetch,
    *,
    now: Callable[[], float] = time.time,
    max_age: float = LIST_REFRESH_SECONDS,
) -> tuple[ListContent, ListState]:
    """The domains and networks of a list: from a copy younger than ``max_age``, otherwise fetched
    anew. A failed fetch keeps the copy in use and says why; a list without a single domain or
    network is refused, so a broken page never replaces a good copy."""
    cached = cache.load(url)
    if cached is not None and now() - cached[1] < max_age:
        content = parse_list(cached[0])
        return content, _state(url, content, cached[1])
    try:
        text = fetch(url)
        content = parse_list(text)
        if content.empty():
            raise ListError(f"{url}: not a single domain or network in it")
        cache.save(url, text)
    except ListError as exc:
        if cached is None:
            return ListContent([], []), ListState(url, 0, None, str(exc))
        content = parse_list(cached[0])
        return content, _state(url, content, cached[1], f"{exc}; the last copy is in use")
    return content, _state(url, content, now())


def _state(url: str, content: ListContent, fetched_at: float, error: str = "") -> ListState:
    return ListState(url, len(content.domains), fetched_at, error, len(content.networks))
