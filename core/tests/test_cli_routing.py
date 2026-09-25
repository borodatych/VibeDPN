"""vibedpn mode / upstream: through core when it runs (nothing restarts), else the file."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from vibedpn import cli
from vibedpn.api import client as core_api
from vibedpn.api.models import RoutingView
from vibedpn.bootstrap import render_config
from vibedpn.config import Config, RoutingMode, Upstream, load_config

from .conftest import client_config, vps_config
from .test_cli_compose import Recorder

runner = CliRunner()


def make_box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: dict[str, object]) -> Recorder:
    recorder = Recorder()
    monkeypatch.setattr(cli, "run", recorder.run)
    monkeypatch.setattr(cli, "capture", recorder.capture)
    monkeypatch.setattr(cli, "preflight", lambda: None)
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    config = Config.model_validate(raw)
    (tmp_path / "config.yaml").write_text(render_config(config), encoding="utf-8")
    return recorder


def core_down(monkeypatch: pytest.MonkeyPatch) -> None:
    def unreachable(*_args: object, **_kwargs: object) -> RoutingView:
        raise core_api.CoreUnreachableError("ConnectError: refused")

    monkeypatch.setattr(core_api, "set_routing", unreachable)


def invoke(tmp_path: Path, *args: str) -> tuple[int, str]:
    result = runner.invoke(cli.app, [*args, "--dir", str(tmp_path)])
    return result.exit_code, result.output


def test_mode_goes_through_core_and_restarts_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = make_box(tmp_path, monkeypatch, client_config())
    asked: list[tuple[int, RoutingMode | None, Upstream | None]] = []

    def set_routing(
        port: int,
        mode: RoutingMode | None,
        upstream: Upstream | None,
        fallback: list[str] | None = None,
    ) -> RoutingView:
        assert fallback is None
        asked.append((port, mode, upstream))
        return RoutingView(mode="off", default_upstream="vps", adguard="applied")

    monkeypatch.setattr(core_api, "set_routing", set_routing)
    before = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    code, output = invoke(tmp_path, "mode", "off")
    assert code == 0, output
    assert (
        "routing: mode=off default_upstream=vps fallback=- (applied live, nothing restarted)"
        in output
    )
    assert asked == [(4480, RoutingMode.OFF, None)]
    assert recorder.calls == []  # no compose restart
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == before  # core writes it


def test_a_silent_adguard_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_box(tmp_path, monkeypatch, client_config())
    monkeypatch.setattr(
        core_api,
        "set_routing",
        lambda *_args, **_kwargs: RoutingView(
            mode="full", default_upstream="vps", adguard="pending"
        ),
    )
    code, output = invoke(tmp_path, "mode", "full")
    assert code == 0 and "AdGuard catches up at the next start of core" in output


def test_a_refusal_of_core_fails_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_box(tmp_path, monkeypatch, client_config())

    def refused(*_args: object, **_kwargs: object) -> RoutingView:
        raise core_api.RoutingRequestError("router refused the change, config.yaml restored: x")

    monkeypatch.setattr(core_api, "set_routing", refused)
    code, output = invoke(tmp_path, "upstream", "dpn")
    assert code == 1 and "config.yaml restored" in output


def test_mode_on_a_stopped_box_only_saves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = make_box(tmp_path, monkeypatch, client_config())
    core_down(monkeypatch)
    code, output = invoke(tmp_path, "mode", "off")
    assert code == 0 and "(saved; core is not running, applies at `vibedpn up`)" in output
    assert recorder.calls == []
    routing = load_config(tmp_path / "config.yaml").routing
    assert routing is not None and routing.mode is RoutingMode.OFF


def test_the_same_mode_touches_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = make_box(tmp_path, monkeypatch, client_config())
    core_down(monkeypatch)
    code, output = invoke(tmp_path, "mode", "full")
    assert code == 0 and "(already set)" in output
    assert recorder.calls == []


def test_smart_is_a_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_box(tmp_path, monkeypatch, client_config())
    core_down(monkeypatch)
    code, output = invoke(tmp_path, "mode", "smart")
    assert code == 0 and "mode=smart" in output
    routing = load_config(tmp_path / "config.yaml").routing
    assert routing is not None and routing.mode is RoutingMode.SMART


def test_a_vps_has_no_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_box(tmp_path, monkeypatch, vps_config())
    core_down(monkeypatch)
    code, output = invoke(tmp_path, "mode", "full")
    assert code == 1 and "no routing section" in output


def test_upstream_to_a_disabled_uplink_is_refused_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = make_box(tmp_path, monkeypatch, client_config())
    core_down(monkeypatch)
    before = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    code, output = invoke(tmp_path, "upstream", "dpn")
    assert code == 1 and "config.yaml not changed" in output and "dpn" in output
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == before
    assert recorder.calls == []


def test_fallback_goes_through_core_as_a_whole_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_box(tmp_path, monkeypatch, client_config())
    asked: list[list[str] | None] = []

    def set_routing(
        _port: int, _mode: object, _upstream: object, fallback: list[str] | None = None
    ) -> RoutingView:
        asked.append(fallback)
        return RoutingView(
            mode="full", default_upstream="vps", fallback=fallback or [], adguard="applied"
        )

    monkeypatch.setattr(core_api, "set_routing", set_routing)
    code, output = invoke(tmp_path, "fallback", "wg-second", "tor")
    assert code == 0 and "fallback=wg-second,tor (applied live" in output
    code, output = invoke(tmp_path, "fallback", "--clear")
    assert code == 0 and "fallback=- (applied live" in output
    assert asked == [["wg-second", "tor"], []]


def test_fallback_without_uplinks_shows_the_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = client_config()
    raw["upstreams"]["tor"] = {"enabled": True}
    raw["routing"]["fallback"] = ["tor"]
    make_box(tmp_path, monkeypatch, raw)
    code, output = invoke(tmp_path, "fallback")
    assert code == 0 and "fallback=tor" in output
    code, output = invoke(tmp_path, "fallback", "tor", "--clear")
    assert code == 1 and "not both" in output


def test_fallback_on_a_stopped_box_is_saved_or_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = client_config()
    raw["upstreams"]["tor"] = {"enabled": True}
    make_box(tmp_path, monkeypatch, raw)
    core_down(monkeypatch)
    code, output = invoke(tmp_path, "fallback", "tor")
    assert code == 0 and "fallback=tor" in output and "(saved;" in output
    routing = load_config(tmp_path / "config.yaml").routing
    assert routing is not None and routing.fallback == ["tor"]
    before = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    code, output = invoke(tmp_path, "fallback", "dpn")  # off on this box
    assert code == 1 and "routing.fallback: 'dpn' is not an enabled uplink" in output
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8") == before
    code, output = invoke(tmp_path, "fallback", "--clear")
    assert code == 0
    routing = load_config(tmp_path / "config.yaml").routing
    assert routing is not None and routing.fallback == []
    assert "\n  fallback:" not in (tmp_path / "config.yaml").read_text(encoding="utf-8")
