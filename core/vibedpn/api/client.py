"""Client of the core API for the CLI.

The CLI never talks to TequilAPI or touches ``secrets/`` itself: ``core`` is the one process
that knows the node and owns the tunnel files (``secrets/`` is root-only), and routing every
reader and writer through it keeps one place to change when the API moves behind the tunnel.
"""

from __future__ import annotations

from urllib.parse import quote

import httpx
from pydantic import TypeAdapter, ValidationError

from vibedpn.api.models import (
    BoxStatus,
    DevicePolicyUpdate,
    DevicePolicyView,
    DeviceView,
    DomainListUpdate,
    DomainListView,
    DomainRuleUpdate,
    DomainRuleView,
    DpnCountryView,
    EventView,
    JournalEntryView,
    LearnedView,
    NetworkRuleUpdate,
    NetworkRuleView,
    PeerCreate,
    PeerFile,
    PeerTraffic,
    PeerView,
    RoutingUpdate,
    RoutingView,
    WifiClientView,
)
from vibedpn.config import DevicePolicy, RoutingMode
from vibedpn.engine.myst import STATS_DEADLINE_SECONDS, ProviderStats

CORE_API_HOST = "127.0.0.1"
# Core may legitimately spend the whole node deadline before answering; wait past it.
CORE_API_TIMEOUT_SECONDS = STATS_DEADLINE_SECONDS + 2.0
VERSION_HINT = "CLI and core versions differ?"
PEER_LIST: TypeAdapter[list[PeerView]] = TypeAdapter(list[PeerView])
TRAFFIC_LIST: TypeAdapter[list[PeerTraffic]] = TypeAdapter(list[PeerTraffic])
DEVICE_LIST: TypeAdapter[list[DeviceView]] = TypeAdapter(list[DeviceView])


class CoreUnreachableError(RuntimeError):
    """``core`` is not listening: the box is down or still starting."""


class CoreNoAnswerError(RuntimeError):
    """``core`` accepted the connection but did not answer in time or in one piece."""


class StatsUnavailableError(RuntimeError):
    """``core`` answered, but without statistics; the text is its ``detail``."""


class PeerRequestError(RuntimeError):
    """``core`` refused or failed a peer request; the text is its ``detail``."""


class DeviceRequestError(RuntimeError):
    """``core`` refused or failed a device request; the text is its ``detail``."""


class RuleRequestError(RuntimeError):
    """Core refused a domain rule or list, or answered something else."""


class RoutingRequestError(RuntimeError):
    """``core`` refused or failed a routing request or has no status; the text is its ``detail``."""


def _send(
    port: int,
    method: str,
    path: str,
    *,
    body: dict[str, str | bool | None] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> httpx.Response:
    url = f"http://{CORE_API_HOST}:{port}{path}"
    try:
        with httpx.Client(
            timeout=CORE_API_TIMEOUT_SECONDS, transport=transport, trust_env=False
        ) as client:
            return client.request(method, url, json=body)
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        raise CoreUnreachableError(f"{exc.__class__.__name__}: {exc}") from exc
    except httpx.HTTPError as exc:
        raise CoreNoAnswerError(f"no answer from core: {exc.__class__.__name__}: {exc}") from exc


def _detail(response: httpx.Response) -> str:
    try:
        body: object = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and isinstance(body.get("detail"), str):
        return str(body["detail"])
    return f"HTTP {response.status_code}"


def fetch_provider_stats(port: int, transport: httpx.BaseTransport | None = None) -> ProviderStats:
    try:
        response = _send(port, "GET", "/provider/stats", transport=transport)
    except CoreNoAnswerError as exc:
        raise StatsUnavailableError(str(exc)) from exc
    if response.status_code != httpx.codes.OK:
        raise StatsUnavailableError(_detail(response))
    try:
        return ProviderStats.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        raise StatsUnavailableError(
            f"core answered something that is not provider stats ({VERSION_HINT})"
        ) from exc


def _peer_request(
    port: int,
    method: str,
    path: str,
    expected: int,
    *,
    body: dict[str, str | bool | None] | None = None,
    transport: httpx.BaseTransport | None = None,
    error: type[RuntimeError] = PeerRequestError,
) -> httpx.Response:
    try:
        response = _send(port, method, path, body=body, transport=transport)
    except CoreNoAnswerError as exc:
        raise error(str(exc)) from exc
    if response.status_code != expected:
        raise error(_detail(response))
    return response


def list_devices(port: int, transport: httpx.BaseTransport | None = None) -> list[DeviceView]:
    response = _peer_request(
        port, "GET", "/devices", httpx.codes.OK, transport=transport, error=DeviceRequestError
    )
    try:
        return DEVICE_LIST.validate_python(response.json())
    except (ValueError, ValidationError) as exc:
        raise DeviceRequestError(
            f"core answered something that is not a device list ({VERSION_HINT})"
        ) from exc


def _peer_file(response: httpx.Response) -> PeerFile:
    try:
        return PeerFile.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        raise PeerRequestError(
            f"core answered something that is not a peer file ({VERSION_HINT})"
        ) from exc


def list_peer_traffic(
    port: int, since: str | None = None, transport: httpx.BaseTransport | None = None
) -> list[PeerTraffic]:
    path = "/peers/traffic" + (f"?since={since}" if since else "")
    response = _peer_request(port, "GET", path, httpx.codes.OK, transport=transport)
    try:
        return TRAFFIC_LIST.validate_python(response.json())
    except (ValueError, ValidationError) as exc:
        raise PeerRequestError(
            f"core answered something that is not a traffic list ({VERSION_HINT})"
        ) from exc


def list_peers(port: int, transport: httpx.BaseTransport | None = None) -> list[PeerView]:
    response = _peer_request(port, "GET", "/peers", httpx.codes.OK, transport=transport)
    try:
        return PEER_LIST.validate_python(response.json())
    except (ValueError, ValidationError) as exc:
        raise PeerRequestError(
            f"core answered something that is not a peer list ({VERSION_HINT})"
        ) from exc


def add_peer(
    port: int,
    name: str,
    transport: httpx.BaseTransport | None = None,
    *,
    tunnel_only: bool = False,
) -> PeerFile:
    body = PeerCreate(name=name, tunnel_only=tunnel_only).model_dump()
    return _peer_file(
        _peer_request(port, "POST", "/peers", httpx.codes.CREATED, body=body, transport=transport)
    )


def export_peer(port: int, name: str, transport: httpx.BaseTransport | None = None) -> PeerFile:
    path = f"/peers/{quote(name, safe='')}/config"
    return _peer_file(_peer_request(port, "GET", path, httpx.codes.OK, transport=transport))


def remove_peer(port: int, name: str, transport: httpx.BaseTransport | None = None) -> None:
    path = f"/peers/{quote(name, safe='')}"
    _peer_request(port, "DELETE", path, httpx.codes.NO_CONTENT, transport=transport)


def set_device(
    port: int,
    ident: str,
    policy: DevicePolicy,
    name: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> DevicePolicyView:
    body = DevicePolicyUpdate(policy=policy, name=name).model_dump(mode="json", exclude_none=True)
    response = _peer_request(
        port,
        "PUT",
        f"/devices/{quote(ident, safe='')}",
        httpx.codes.OK,
        body=body,
        transport=transport,
        error=DeviceRequestError,
    )
    try:
        return DevicePolicyView.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        raise DeviceRequestError(
            f"core answered something that is not a device policy ({VERSION_HINT})"
        ) from exc


def unset_device(port: int, ident: str, transport: httpx.BaseTransport | None = None) -> None:
    _peer_request(
        port,
        "DELETE",
        f"/devices/{quote(ident, safe='')}",
        httpx.codes.NO_CONTENT,
        transport=transport,
        error=DeviceRequestError,
    )


def set_routing(
    port: int,
    mode: RoutingMode | None = None,
    upstream: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> RoutingView:
    body = RoutingUpdate.model_validate(
        {"mode": None if mode is None else mode.value, "default_upstream": upstream}
    ).model_dump(mode="json", exclude_none=True)
    response = _send(port, "PUT", "/routing", body=body, transport=transport)
    if response.status_code != httpx.codes.OK:
        raise RoutingRequestError(_detail(response))
    try:
        return RoutingView.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        raise RoutingRequestError(
            f"core answered something that is not routing ({VERSION_HINT})"
        ) from exc


def fetch_status(port: int, transport: httpx.BaseTransport | None = None) -> BoxStatus:
    response = _send(port, "GET", "/status", transport=transport)
    if response.status_code != httpx.codes.OK:
        raise RoutingRequestError(_detail(response))
    try:
        return BoxStatus.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        raise RoutingRequestError(
            f"core answered something that is not a status ({VERSION_HINT})"
        ) from exc


def set_dpn_country(
    port: int, country: str | None, transport: httpx.BaseTransport | None = None
) -> DpnCountryView:
    response = _send(port, "PUT", "/dpn/country", body={"country": country}, transport=transport)
    if response.status_code != httpx.codes.OK:
        raise RoutingRequestError(_detail(response))
    try:
        return DpnCountryView.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        raise RoutingRequestError(
            f"core answered something that is not a dpn country ({VERSION_HINT})"
        ) from exc


def list_rules(port: int, transport: httpx.BaseTransport | None = None) -> list[DomainRuleView]:
    response = _peer_request(
        port, "GET", "/rules", httpx.codes.OK, transport=transport, error=RuleRequestError
    )
    try:
        return [DomainRuleView.model_validate(item) for item in response.json()]
    except (ValueError, ValidationError, TypeError) as exc:
        raise RuleRequestError(
            f"core answered something that is not rules ({VERSION_HINT})"
        ) from exc


def set_rule(
    port: int,
    domain: str,
    update: DomainRuleUpdate,
    transport: httpx.BaseTransport | None = None,
) -> DomainRuleView:
    response = _peer_request(
        port,
        "PUT",
        f"/rules/{quote(domain, safe='')}",
        httpx.codes.OK,
        body=update.model_dump(mode="json"),
        transport=transport,
        error=RuleRequestError,
    )
    try:
        return DomainRuleView.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        raise RuleRequestError(
            f"core answered something that is not a rule ({VERSION_HINT})"
        ) from exc


def remove_rule(port: int, domain: str, transport: httpx.BaseTransport | None = None) -> None:
    _peer_request(
        port,
        "DELETE",
        f"/rules/{quote(domain, safe='')}",
        httpx.codes.NO_CONTENT,
        transport=transport,
        error=RuleRequestError,
    )


def journal(
    port: int, client: str, since: float, transport: httpx.BaseTransport | None = None
) -> list[JournalEntryView]:
    response = _peer_request(
        port,
        "GET",
        f"/dns/journal/{quote(client, safe='')}?since={since}",
        httpx.codes.OK,
        transport=transport,
        error=RuleRequestError,
    )
    try:
        return [JournalEntryView.model_validate(item) for item in response.json()]
    except (ValueError, ValidationError, TypeError) as exc:
        raise RuleRequestError(
            f"core answered something that is not a journal ({VERSION_HINT})"
        ) from exc


def learned_names(port: int, transport: httpx.BaseTransport | None = None) -> list[LearnedView]:
    response = _peer_request(
        port, "GET", "/learned", httpx.codes.OK, transport=transport, error=RuleRequestError
    )
    try:
        return [LearnedView.model_validate(item) for item in response.json()]
    except (ValueError, ValidationError, TypeError) as exc:
        raise RuleRequestError(
            f"core answered something that is not learned names ({VERSION_HINT})"
        ) from exc


def forget_learned(port: int, name: str, transport: httpx.BaseTransport | None = None) -> None:
    _peer_request(
        port,
        "DELETE",
        f"/learned/{quote(name, safe='')}",
        httpx.codes.NO_CONTENT,
        transport=transport,
        error=RuleRequestError,
    )


def list_domain_lists(
    port: int, transport: httpx.BaseTransport | None = None
) -> list[DomainListView]:
    response = _peer_request(
        port, "GET", "/lists", httpx.codes.OK, transport=transport, error=RuleRequestError
    )
    try:
        return [DomainListView.model_validate(item) for item in response.json()]
    except (ValueError, ValidationError, TypeError) as exc:
        raise RuleRequestError(
            f"core answered something that is not domain lists ({VERSION_HINT})"
        ) from exc


def list_network_rules(
    port: int, transport: httpx.BaseTransport | None = None
) -> list[NetworkRuleView]:
    response = _peer_request(
        port, "GET", "/networks", httpx.codes.OK, transport=transport, error=RuleRequestError
    )
    try:
        return [NetworkRuleView.model_validate(item) for item in response.json()]
    except (ValueError, ValidationError, TypeError) as exc:
        raise RuleRequestError(
            f"core answered something that is not network rules ({VERSION_HINT})"
        ) from exc


def set_network_rule(
    port: int, update: NetworkRuleUpdate, transport: httpx.BaseTransport | None = None
) -> NetworkRuleView:
    response = _peer_request(
        port,
        "PUT",
        "/networks",
        httpx.codes.OK,
        body=update.model_dump(mode="json"),
        transport=transport,
        error=RuleRequestError,
    )
    try:
        return NetworkRuleView.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        raise RuleRequestError(
            f"core answered something that is not a network rule ({VERSION_HINT})"
        ) from exc


def remove_network_rule(
    port: int, network: str, transport: httpx.BaseTransport | None = None
) -> None:
    _peer_request(
        port,
        "DELETE",
        f"/networks?network={quote(network, safe='')}",
        httpx.codes.NO_CONTENT,
        transport=transport,
        error=RuleRequestError,
    )


def set_domain_list(
    port: int, update: DomainListUpdate, transport: httpx.BaseTransport | None = None
) -> DomainListView:
    response = _peer_request(
        port,
        "PUT",
        "/lists",
        httpx.codes.OK,
        body=update.model_dump(mode="json"),
        transport=transport,
        error=RuleRequestError,
    )
    try:
        return DomainListView.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        raise RuleRequestError(
            f"core answered something that is not a domain list ({VERSION_HINT})"
        ) from exc


def remove_domain_list(port: int, url: str, transport: httpx.BaseTransport | None = None) -> None:
    _peer_request(
        port,
        "DELETE",
        f"/lists?url={quote(url, safe='')}",
        httpx.codes.NO_CONTENT,
        transport=transport,
        error=RuleRequestError,
    )


class EventRequestError(RuntimeError):
    """Core refused or failed a journal or Wi-Fi request; the text is its ``detail``."""


EVENT_LIST: TypeAdapter[list[EventView]] = TypeAdapter(list[EventView])
WIFI_CLIENT_LIST: TypeAdapter[list[WifiClientView]] = TypeAdapter(list[WifiClientView])


def list_events(
    port: int,
    kind: str | None = None,
    since: float | None = None,
    limit: int | None = None,
    transport: httpx.BaseTransport | None = None,
) -> list[EventView]:
    query = "&".join(
        f"{key}={quote(str(value), safe='')}"
        for key, value in (("kind", kind), ("since", since), ("limit", limit))
        if value is not None
    )
    path = f"/events?{query}" if query else "/events"
    response = _peer_request(
        port, "GET", path, httpx.codes.OK, transport=transport, error=EventRequestError
    )
    try:
        return EVENT_LIST.validate_python(response.json())
    except (ValueError, ValidationError) as exc:
        raise EventRequestError(
            f"core answered something that is not an event list ({VERSION_HINT})"
        ) from exc


def list_wifi_clients(
    port: int, transport: httpx.BaseTransport | None = None
) -> list[WifiClientView]:
    response = _peer_request(
        port, "GET", "/wifi/clients", httpx.codes.OK, transport=transport, error=EventRequestError
    )
    try:
        return WIFI_CLIENT_LIST.validate_python(response.json())
    except (ValueError, ValidationError) as exc:
        raise EventRequestError(
            f"core answered something that is not a Wi-Fi client list ({VERSION_HINT})"
        ) from exc
