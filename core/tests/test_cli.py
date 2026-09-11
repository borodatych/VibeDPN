"""CLI entry point."""

from typer.testing import CliRunner

from vibedpn import __version__
from vibedpn.cli import app


def test_version_flag() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"vibedpn {__version__}"


def test_no_args_shows_help() -> None:
    result = CliRunner().invoke(app, [])
    assert "VibeDPN" in result.output
