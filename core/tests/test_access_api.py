"""The access server and ddns through the API: what the panel and the CLI do with them."""

from contextlib import closing
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from vibedpn.api.app import create_app
from vibedpn.api.state import BoxState
from vibedpn.api.traffic import ACCESS_TRAFFIC_DIR
from vibedpn.bootstrap import render_config
from vibedpn.config import Config, load_config
from vibedpn.engine.access import PEOPLE_TABLE_FILE, list_people
from vibedpn.engine.traffic import Sample, connect, record
from vibedpn.engine.xray import parse_share_link

from .conftest import home_config

TOKEN = "s3cr3t-t0ken-of-the-owner"
UPDATE_URL = f"https://www.duckdns.org/update?domains=myhome&token={TOKEN}&ip={{ip}}"


def box(tmp_path: Path, raw: dict[str, Any] | None = None) -> tuple[TestClient, Path]:
    config = Config.model_validate(raw or home_config())
    path = tmp_path / "config.yaml"
    path.write_text(render_config(config), encoding="utf-8")
    (tmp_path / "secrets").mkdir(mode=0o700)
    (tmp_path / "data").mkdir()
    state = BoxState(config, path, apply=lambda _config: [])
    app = create_app(
        config,
        state=state,
        secrets_dir=tmp_path / "secrets",
        data_dir=tmp_path / "data",
        access_dir=tmp_path / "access",
        access_owner=None,
    )
    return TestClient(app), path


def test_the_server_is_off_until_the_owner_turns_it_on(tmp_path: Path) -> None:
    client, path = box(tmp_path)
    shown = client.get("/access").json()
    assert shown["enabled"] is False and shown["people"] == []
    refused = client.post("/access/people", json={"name": "anna"})
    assert refused.status_code == 409 and "access enable" in refused.text
    # a box at home needs the name its people dial
    no_name = client.put("/access", json={"enabled": True})
    assert no_name.status_code == 422 and "access.address" in no_name.text
    assert not load_config(path).access.enabled


def test_turning_it_on_renders_the_server_and_asks_the_host(tmp_path: Path) -> None:
    client, path = box(tmp_path)
    answer = client.put("/access", json={"enabled": True, "address": "myhome.duckdns.org"})
    assert answer.status_code == 200, answer.text
    shown = answer.json()
    assert (shown["enabled"], shown["address"], shown["port"]) == (True, "myhome.duckdns.org", 443)
    assert shown["apply"]["pending"] is True  # the host starts the container
    assert load_config(path).access.enabled
    assert (tmp_path / "access" / "config.json").is_file()


def test_a_person_gets_a_link_and_a_qr_code_and_the_server_gets_them(tmp_path: Path) -> None:
    client, _ = box(tmp_path)
    client.put("/access", json={"enabled": True, "address": "myhome.duckdns.org"})
    created = client.post("/access/people", json={"name": "anna"})
    assert created.status_code == 201, created.text
    body = created.json()
    server = parse_share_link(body["link"])
    assert (server.host, server.port, server.security) == ("myhome.duckdns.org", 443, "reality")
    # a light background under the code: the panel may be dark, and a camera needs contrast
    assert body["qr_svg"].startswith("<svg") and 'path fill="#fff"' in body["qr_svg"]
    # the panel shows it as an image: without its namespace an SVG image draws nothing
    assert 'xmlns="http://www.w3.org/2000/svg"' in body["qr_svg"]
    assert "anna\t" in (tmp_path / "access" / PEOPLE_TABLE_FILE).read_text()
    again = client.get("/access/people/anna")
    assert again.status_code == 200 and again.json()["link"] == body["link"]
    # the list never shows the id: it is what lets a person in
    listed = client.get("/access")
    assert [person["name"] for person in listed.json()["people"]] == ["anna"]
    assert server.uuid not in listed.text


def test_names_are_refused_by_reason(tmp_path: Path) -> None:
    client, _ = box(tmp_path)
    client.put("/access", json={"enabled": True, "address": "myhome.duckdns.org"})
    client.post("/access/people", json={"name": "anna"})
    assert client.post("/access/people", json={"name": "anna"}).status_code == 409
    assert client.post("/access/people", json={"name": "Anna Smith"}).status_code == 422
    assert client.get("/access/people/nobody").status_code == 404


def test_traffic_is_shown_per_person_and_goes_with_them(tmp_path: Path) -> None:
    client, _ = box(tmp_path)
    client.put("/access", json={"enabled": True, "address": "myhome.duckdns.org"})
    client.post("/access/people", json={"name": "anna"})
    anna = list_people(tmp_path / "secrets")[0]
    with closing(connect(tmp_path / "data" / ACCESS_TRAFFIC_DIR)) as connection:
        record(connection, [Sample(anna.id, 2_000, 9_000)], 1_790_000_000.0)
    person = client.get("/access").json()["people"][0]
    assert (person["rx_bytes"], person["tx_bytes"]) == (2_000, 9_000)
    assert client.delete("/access/people/anna").status_code == 204
    assert client.get("/access/people/anna").status_code == 404
    client.post("/access/people", json={"name": "anna"})
    fresh = client.get("/access").json()["people"][0]
    assert (fresh["rx_bytes"], fresh["tx_bytes"]) == (0, 0)  # a new anna starts from zero


def test_ddns_takes_the_url_and_never_gives_it_back(tmp_path: Path) -> None:
    client, path = box(tmp_path)
    refused = client.put("/ddns", json={"enabled": True})
    assert refused.status_code == 422 and "no update URL" in refused.text
    plain = client.put("/ddns", json={"enabled": True, "url": "http://www.duckdns.org/update"})
    assert plain.status_code == 422 and "https://" in plain.text
    answer = client.put("/ddns", json={"enabled": True, "url": UPDATE_URL})
    assert answer.status_code == 200, answer.text
    shown = answer.json()
    assert (shown["enabled"], shown["url_set"], shown["host"]) == (True, True, "www.duckdns.org")
    assert TOKEN not in answer.text and TOKEN not in client.get("/ddns").text
    assert (tmp_path / "secrets" / "ddns-url").read_text().strip() == UPDATE_URL
    assert load_config(path).ddns.enabled
    off = client.put("/ddns", json={"enabled": False})
    assert off.json()["enabled"] is False and off.json()["url_set"] is True  # kept for later
