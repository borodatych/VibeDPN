"""The access server and ddns on the host: doctor, config edits, the CLI, the counters it reads."""

import stat
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from vibedpn import cli
from vibedpn.api import client as core_api
from vibedpn.api import traffic
from vibedpn.api.models import AccessLink, AccessPerson, AccessView, ApplyView
from vibedpn.bootstrap import render_config
from vibedpn.compose import ServiceStatus
from vibedpn.config import Config, load_config
from vibedpn.config_edit import set_access, set_ddns
from vibedpn.doctor import (
    DIRECT_EXIT,
    AccessFacts,
    CheckResult,
    DoctorFacts,
    ExitFact,
    Verdict,
    evaluate,
    port_needs,
)
from vibedpn.engine import access
from vibedpn.engine.ddns import URL_FILE, DdnsState
from vibedpn.engine.traffic import Sample

from .conftest import home_config

runner = CliRunner()
ADDRESS = "myhome.duckdns.org"


def home_with(**sections: object) -> Config:
    return Config.model_validate({**home_config(), **sections})


def facts(config: Config, access_facts: AccessFacts, **overrides: object) -> DoctorFacts:
    base: dict[str, object] = {
        "config": config,
        "config_error": "",
        "config_hint": "",
        "env_current": True,
        "secrets": {},
        "wireguard": True,
        "nf_tables": True,
        "ip_forward": True,
        "listeners": [],
        "is_root": True,
        "docker_error": "",
        "services": [ServiceStatus("core", "running", "healthy", "Up")],
        "active_services": ["core"],
        "access": access_facts,
    }
    base.update(overrides)
    return DoctorFacts(**base)  # type: ignore[arg-type]


def result(results: list[CheckResult], name: str) -> CheckResult:
    return next(item for item in results if item.name == name)


# --- doctor ------------------------------------------------------------------------------------

ON = {"access": {"enabled": True, "address": ADDRESS}}


def test_doctor_fails_a_box_whose_router_does_not_steer_the_server() -> None:
    missing = evaluate(facts(home_with(**ON), AccessFacts(chain=False)))
    assert result(missing, "access").verdict is Verdict.FAIL
    assert "access_output" in result(missing, "access").detail
    fine = evaluate(facts(home_with(**ON), AccessFacts(chain=True)))
    assert result(fine, "access").verdict is Verdict.OK
    unknown = evaluate(facts(home_with(**ON), AccessFacts(chain=None)))
    assert result(unknown, "access").verdict is Verdict.WARN


def test_doctor_says_nothing_of_a_server_that_is_off() -> None:
    names = {item.name for item in evaluate(facts(home_with(), AccessFacts()))}
    assert "access" not in names and "ddns" not in names


def test_with_network_the_name_must_lead_to_this_box() -> None:
    here = [ExitFact(DIRECT_EXIT, "203.0.113.5")]
    leads = evaluate(
        facts(home_with(**ON), AccessFacts(chain=True, resolved=["203.0.113.5"]), exits=here)
    )
    assert result(leads, "access name").verdict is Verdict.OK
    elsewhere = evaluate(
        facts(home_with(**ON), AccessFacts(chain=True, resolved=["198.51.100.1"]), exits=here)
    )
    assert result(elsewhere, "access name").verdict is Verdict.WARN
    unresolved = evaluate(
        facts(
            home_with(**ON),
            AccessFacts(chain=True, resolved=[], resolve_error="Name or service not known"),
            exits=here,
        )
    )
    assert result(unresolved, "access name").verdict is Verdict.FAIL


@pytest.mark.parametrize(
    ("ddns_facts", "verdict"),
    [
        (AccessFacts(ddns_url=False), Verdict.FAIL),
        (AccessFacts(ddns_url=True), Verdict.WARN),  # core has not called it yet
        (
            AccessFacts(
                ddns_url=True,
                ddns_state=DdnsState(last_ok=False, last_at=1.0, message="200 KO"),
            ),
            Verdict.FAIL,
        ),
        (
            AccessFacts(
                ddns_url=True,
                ddns_state=DdnsState(
                    public_ip="203.0.113.9", told_ip="203.0.113.5", last_ok=True, last_at=1.0
                ),
            ),
            Verdict.WARN,
        ),
        (
            AccessFacts(
                ddns_url=True,
                ddns_state=DdnsState(
                    public_ip="203.0.113.5", told_ip="203.0.113.5", last_ok=True, last_at=1.0
                ),
            ),
            Verdict.OK,
        ),
    ],
)
def test_doctor_reads_how_the_last_ddns_call_went(
    ddns_facts: AccessFacts, verdict: Verdict
) -> None:
    config = home_with(ddns={"enabled": True})
    assert result(evaluate(facts(config, ddns_facts)), "ddns").verdict is verdict


def test_the_ports_of_the_server_are_claimed() -> None:
    needs = {(need.service, need.proto, need.port) for need in port_needs(home_with(**ON))}
    assert {("access", "tcp", 443), ("access", "tcp", access.API_PORT)} <= needs


# --- config edits ------------------------------------------------------------------------------


def test_edits_add_the_sections_to_a_config_written_before_they_existed(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    text = render_config(home_with())
    # a box set up before the access server knew nothing of these sections
    old = text.split("\n# Сервер доступа")[0] + "\n" + text.split("\nddns:\n  enabled: false\n")[1]
    path.write_text(old, encoding="utf-8")
    assert "\naccess:" not in path.read_text() and "\nddns:" not in path.read_text()
    config, changed = set_access(path, enabled=True, address=ADDRESS, target="www.apple.com")
    assert changed and config.access.enabled and config.access.target == "www.apple.com"
    config, _ = set_ddns(path, True)
    assert load_config(path).ddns.enabled and load_config(path).access.address == ADDRESS


# --- CLI ---------------------------------------------------------------------------------------


def box(tmp_path: Path, config: Config) -> Path:
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    (tmp_path / "config.yaml").write_text(render_config(config), encoding="utf-8")
    return tmp_path


def test_enable_edits_the_config_and_names_the_next_steps(tmp_path: Path) -> None:
    directory = box(tmp_path, home_with())
    answer = runner.invoke(
        cli.app, ["access", "enable", "--address", ADDRESS, "--dir", str(directory)]
    )
    assert answer.exit_code == 0, answer.output
    assert "forward TCP 443" in answer.output and "vibedpn access add" in answer.output
    assert load_config(directory / "config.yaml").access.enabled
    off = runner.invoke(cli.app, ["access", "disable", "--dir", str(directory)])
    assert off.exit_code == 0 and not load_config(directory / "config.yaml").access.enabled


def test_add_prints_the_link_and_its_qr_code_or_writes_a_private_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = box(tmp_path, home_with(**ON))
    link = AccessLink(name="anna", link="vless://id@myhome.duckdns.org:443?x#anna", qr_svg="<svg/>")
    monkeypatch.setattr(core_api, "add_person", lambda _port, _name: link)
    printed = runner.invoke(cli.app, ["access", "add", "anna", "--dir", str(directory)])
    assert printed.exit_code == 0 and link.link in printed.output
    target = tmp_path / "anna.txt"
    written = runner.invoke(
        cli.app, ["access", "add", "anna", "--out", str(target), "--dir", str(directory)]
    )
    assert written.exit_code == 0, written.output
    assert target.read_text().strip() == link.link
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_list_shows_people_with_their_traffic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = box(tmp_path, home_with(**ON))
    view = AccessView(
        enabled=True,
        address=ADDRESS,
        port=443,
        target="dl.google.com",
        people=[
            AccessPerson(
                name="anna", created=datetime(2026, 9, 23, tzinfo=UTC), rx_bytes=1, tx_bytes=2
            )
        ],
        apply=ApplyView(pending=False, ok=None, message="", finished_at=None),
    )
    monkeypatch.setattr(core_api, "get_access", lambda _port, _since: view)
    listed = runner.invoke(cli.app, ["access", "list", "--dir", str(directory)])
    assert listed.exit_code == 0
    assert "anna" in listed.output and "2026-09-23" in listed.output and ADDRESS in listed.output


def test_ddns_set_takes_the_url_from_a_file_and_keeps_it_private(tmp_path: Path) -> None:
    directory = box(tmp_path, home_with())
    source = tmp_path / "url.txt"
    source.write_text("https://www.duckdns.org/update?domains=myhome&token=t0k\n")
    answer = runner.invoke(
        cli.app, ["ddns", "set", "--url-file", str(source), "--dir", str(directory)]
    )
    assert answer.exit_code == 0, answer.output
    assert "t0k" not in answer.output and "www.duckdns.org" in answer.output
    kept = directory / "secrets" / URL_FILE
    assert stat.S_IMODE(kept.stat().st_mode) == 0o600
    assert load_config(directory / "config.yaml").ddns.enabled
    refused = tmp_path / "plain.txt"
    refused.write_text("http://www.duckdns.org/update?token=t0k\n")
    bad = runner.invoke(
        cli.app, ["ddns", "set", "--url-file", str(refused), "--dir", str(directory)]
    )
    assert bad.exit_code != 0 and "https://" in bad.output


# --- the counters core reads -------------------------------------------------------------------


def test_the_counters_are_per_person_and_the_health_check_is_nobody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = home_with(**ON)
    anna, _ = access.add_person(config, tmp_path, tmp_path / "access", "anna", owner=None)
    published = {
        "stats": {
            "user": {
                "anna": {"uplink": 100, "downlink": 900},
                access.HEALTH_EMAIL: {"uplink": 5, "downlink": 5},
                "someone-removed": {"uplink": 1, "downlink": 1},
            }
        }
    }
    monkeypatch.setattr(httpx, "get", lambda *_args, **_kwargs: httpx.Response(200, json=published))
    assert traffic.access_samples(tmp_path) == [Sample(anna.id, 100, 900)]


def test_a_server_that_does_not_answer_gives_no_sample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_args: object, **_kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", refuse)
    assert traffic.access_samples(tmp_path) is None
