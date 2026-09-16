"""Domain rules through core: written into config.yaml with its comments, applied live."""

from pathlib import Path

from fastapi.testclient import TestClient

from vibedpn.api.app import create_app
from vibedpn.api.state import BoxState
from vibedpn.bootstrap import render_config
from vibedpn.config import Config, Upstream, load_config

from .conftest import client_config


def rules_box(tmp_path: Path) -> tuple[TestClient, BoxState, list[Config]]:
    raw = client_config()
    raw["upstreams"]["dpn"] = {"enabled": True}
    path = tmp_path / "config.yaml"
    path.write_text("# owner note\n" + render_config(Config.model_validate(raw)), encoding="utf-8")
    applied: list[Config] = []

    def apply(config: Config) -> list[Upstream]:
        applied.append(config)
        return []

    state = BoxState(load_config(path), path, apply=apply)
    return TestClient(create_app(state.config, state=state)), state, applied


def test_a_rule_is_added_replaced_listed_and_removed(tmp_path: Path) -> None:
    client, state, applied = rules_box(tmp_path)
    added = client.put("/rules/Kinopoisk.RU", json={"via": "dpn", "also": ["strm.yandex.net"]})
    assert added.status_code == 200, added.text
    assert added.json() == {
        "domain": "kinopoisk.ru",
        "via": "dpn",
        "country": None,
        "uplink": None,
        "learn": True,
        "also": ["strm.yandex.net"],
    }
    replaced = client.put("/rules/kinopoisk.ru", json={"via": "direct", "learn": False})
    assert replaced.json()["via"] == "direct" and replaced.json()["also"] == []
    client.put("/rules/netflix.com", json={"via": "vps"})
    assert [rule["domain"] for rule in client.get("/rules").json()] == [
        "kinopoisk.ru",
        "netflix.com",
    ]
    routing = load_config(state.path).routing
    assert routing is not None and [rule.via.value for rule in routing.domains] == ["direct", "vps"]
    assert state.path.read_text(encoding="utf-8").startswith("# owner note\n")
    assert len(applied) == 3  # every change applied live
    assert client.delete("/rules/netflix.com").status_code == 204
    assert client.delete("/rules/netflix.com").status_code == 404
    assert [rule["domain"] for rule in client.get("/rules").json()] == ["kinopoisk.ru"]


def test_a_bad_rule_changes_nothing(tmp_path: Path) -> None:
    client, state, applied = rules_box(tmp_path)
    before = state.path.read_text(encoding="utf-8")
    assert client.put("/rules/not a domain", json={"via": "vps"}).status_code == 422
    assert (
        client.put("/rules/a.example", json={"via": "direct", "country": "DE"}).status_code == 422
    )
    assert state.path.read_text(encoding="utf-8") == before and applied == []
