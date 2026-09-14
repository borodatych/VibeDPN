"""vibedpn rule add|rm|list: through core, readable lines, core failures as one error line."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from vibedpn import cli
from vibedpn.api import client as core_api
from vibedpn.api.models import DomainRuleUpdate, DomainRuleView

from .conftest import client_config
from .test_cli_routing import make_box

runner = CliRunner()


def test_rule_add_list_rm_go_through_core(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_box(tmp_path, monkeypatch, client_config())
    rules: dict[str, DomainRuleView] = {}

    def set_rule(_port: int, domain: str, update: DomainRuleUpdate) -> DomainRuleView:
        view = DomainRuleView(domain=domain.lower(), **update.model_dump())
        rules[view.domain] = view
        return view

    def remove_rule(_port: int, domain: str) -> None:
        if rules.pop(domain, None) is None:
            raise core_api.RuleRequestError(f"config.yaml has no rule for {domain}")

    monkeypatch.setattr(core_api, "set_rule", set_rule)
    monkeypatch.setattr(core_api, "remove_rule", remove_rule)
    monkeypatch.setattr(core_api, "list_rules", lambda _port: list(rules.values()))
    added = runner.invoke(
        cli.app,
        [
            "rule",
            "add",
            "Kinopoisk.ru",
            "dpn",
            "--country",
            "DE",
            "--also",
            "strm.yandex.net",
            "--dir",
            str(tmp_path),
        ],
    )
    assert added.exit_code == 0, added.output
    assert "kinopoisk.ru: via dpn DE, applied" in added.output
    listed = runner.invoke(cli.app, ["rule", "list", "--dir", str(tmp_path)])
    assert "kinopoisk.ru  dpn DE  (also strm.yandex.net)" in listed.output
    assert (
        runner.invoke(cli.app, ["rule", "rm", "kinopoisk.ru", "--dir", str(tmp_path)]).exit_code
        == 0
    )
    missing = runner.invoke(cli.app, ["rule", "rm", "kinopoisk.ru", "--dir", str(tmp_path)])
    assert missing.exit_code == 1 and "no rule for kinopoisk.ru" in missing.output
    empty = runner.invoke(cli.app, ["rule", "list", "--dir", str(tmp_path)])
    assert "no domain rules" in empty.output
