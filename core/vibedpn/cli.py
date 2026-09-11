"""``vibedpn`` command line: a thin client over ``core`` and Docker Compose.

Stage 0 ships the application object and ``--version``; commands arrive with Stage 1
(``init``, ``up``, ``down``, ``restart``, ``status``, ``logs``, ``doctor``).
"""

from typing import Annotated

import typer

from vibedpn import __version__

app = typer.Typer(
    name="vibedpn",
    help="VibeDPN: one box, one command. Provider node, private tunnel, LAN router.",
    add_completion=False,
    no_args_is_help=True,
)


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"vibedpn {__version__}")
        raise typer.Exit


@app.callback(invoke_without_command=True)
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            help="Show the version and exit.",
            callback=_print_version,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """VibeDPN: one box, one command. Provider node, private tunnel, LAN router."""
