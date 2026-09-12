"""Docker Compose over the box directory.

Pure parts (argv building, precondition checks, ``ps`` parsing) are unit-tested; ``run`` and
``preflight`` are the only functions that execute anything.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from vibedpn.bootstrap import (
    CONFIG_FILE,
    ENV_FILE,
    PUBLIC_FILE_MODE,
    preserved_env,
    render_env,
    write_file,
)
from vibedpn.config import Config, ConfigError, load_config

COMPOSE_FILE = "compose.yaml"
DEFAULT_LOG_TAIL = 100


class ComposeError(RuntimeError):
    """A user-facing reason why Compose cannot be driven."""


@dataclass(frozen=True)
class ServiceStatus:
    service: str
    state: str
    health: str
    status: str


def compose_argv(box_dir: Path, *args: str, all_profiles: bool = False) -> list[str]:
    """``docker compose`` invocation rooted at the box directory (``.env`` is read from there)."""
    argv = ["docker", "compose", "--project-directory", str(box_dir)]
    if all_profiles:
        argv += ["--profile", "*"]
    return argv + list(args)


def check_box(box_dir: Path) -> Config:
    """The box directory must be a checkout with a valid ``config.yaml``."""
    if not (box_dir / COMPOSE_FILE).is_file():
        raise ComposeError(
            f"{box_dir} is not a VibeDPN checkout (no {COMPOSE_FILE}); run install.sh"
        )
    if not (box_dir / CONFIG_FILE).is_file():
        raise ComposeError(f"no {CONFIG_FILE} in {box_dir}; run `vibedpn init` first")
    try:
        return load_config(box_dir / CONFIG_FILE)
    except (ConfigError, ValidationError) as exc:
        raise ComposeError(f"{CONFIG_FILE} is invalid: {exc}") from None


def refresh_env(box_dir: Path, config: Config) -> Path:
    """Re-derive ``.env`` from ``config.yaml`` so hand edits to the config take effect."""
    env_path = box_dir / ENV_FILE
    try:
        return write_file(env_path, render_env(config, preserved_env(env_path)), PUBLIC_FILE_MODE)
    except OSError as exc:
        raise ComposeError(f"cannot write {env_path}: {exc.strerror}; run with sudo?") from exc


def parse_ps(output: str) -> list[ServiceStatus]:
    """``docker compose ps --format json``: one JSON object per line, or one JSON array."""
    text = output.strip()
    if not text:
        return []
    try:
        loaded = json.loads(text)
        records = loaded if isinstance(loaded, list) else [loaded]
    except json.JSONDecodeError:
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
    return [
        ServiceStatus(
            service=str(record.get("Service", "?")),
            state=str(record.get("State", "?")),
            health=str(record.get("Health", "") or "-"),
            status=str(record.get("Status", "")),
        )
        for record in records
    ]


def preflight() -> None:
    """One readable error instead of Docker's own when the CLI or the daemon is unreachable."""
    try:
        probe = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ComposeError("docker not found; run install.sh") from exc
    if probe.returncode == 0:
        return
    stderr = probe.stderr.strip()
    if "permission denied" in stderr.lower():
        raise ComposeError(
            "no access to the Docker socket: log out and in again after install.sh added you"
            " to the docker group, or run with sudo"
        )
    if "cannot connect" in stderr.lower():
        raise ComposeError("the Docker daemon is not running: sudo systemctl start docker")
    raise ComposeError(f"docker is not usable: {stderr}")


def run(argv: list[str]) -> int:
    """Run Compose with inherited stdio so the user sees its output live; return its exit code."""
    try:
        return subprocess.run(argv, check=False).returncode
    except FileNotFoundError as exc:
        raise ComposeError("docker not found; run install.sh") from exc


def capture(argv: list[str]) -> str:
    """Run Compose and return stdout; a failure becomes a ``ComposeError`` with its stderr."""
    try:
        completed = subprocess.run(argv, check=False, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise ComposeError("docker not found; run install.sh") from exc
    if completed.returncode != 0:
        raise ComposeError(
            completed.stderr.strip() or f"docker compose exited {completed.returncode}"
        )
    return completed.stdout
