"""Docker Compose over the box directory.

Pure parts (argv building, precondition checks, ``ps`` parsing) are unit-tested; ``run`` and
``preflight`` are the only functions that execute anything.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from vibedpn.bootstrap import (
    CONFIG_FILE,
    ENV_FILE,
    PUBLIC_FILE_MODE,
    checkout_image_tag,
    give_to_invoker,
    preserved_env,
    render_env,
    required_secrets,
    secrets_present,
    write_file,
)
from vibedpn.config import Config, ConfigError, load_config

COMPOSE_FILE = "compose.yaml"
DEFAULT_LOG_TAIL = 100
# Before 28.0.0 ports published on 127.0.0.1 were reachable from L2 neighbours (Docker release
# notes 28.0.0), and nat-unprotected did not exist; the box relies on both.
MIN_DOCKER_ENGINE = (28, 0, 0)
ENGINE_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")


class ComposeError(RuntimeError):
    """A user-facing reason why Compose cannot be driven, with the command that fixes it."""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(f"{message}; {hint}" if hint else message)
        self.message = message
        self.hint = hint


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
            f"{box_dir} is not a VibeDPN checkout (no {COMPOSE_FILE})", "run install.sh"
        )
    if not (box_dir / CONFIG_FILE).is_file():
        raise ComposeError(f"no {CONFIG_FILE} in {box_dir}", "run `vibedpn init` first")
    try:
        return load_config(box_dir / CONFIG_FILE)
    except (ConfigError, ValidationError) as exc:
        raise ComposeError(
            f"{CONFIG_FILE} is invalid: {exc}",
            f"fix that key in {CONFIG_FILE} (docs/manuals/configSpec.md)",
        ) from None


def check_secrets(box_dir: Path, config: Config) -> None:
    """Refuse to start a box whose secrets are missing: the node would fall back to its public
    default password. A secret that cannot be stat-ed (root-only dir, not root) is not a failure."""
    present = secrets_present(box_dir)
    missing = [name for name in required_secrets(config) if present.get(name) is False]
    if missing:
        raise ComposeError(
            f"missing {', '.join(missing)}", "run `sudo vibedpn init --force` to create it"
        )


def engine_too_old(version: str) -> bool:
    """``True`` for a parseable Engine version below the floor; unknown strings never block."""
    match = ENGINE_VERSION.match(version.strip())
    if match is None:
        return False
    return tuple(int(part) for part in match.groups()) < MIN_DOCKER_ENGINE


def refresh_env(box_dir: Path, config: Config) -> Path:
    """Re-derive ``.env`` from ``config.yaml`` so hand edits to the config take effect."""
    env_path = box_dir / ENV_FILE
    preserved = preserved_env(env_path, checkout_image_tag(box_dir))
    try:
        write_file(env_path, render_env(config, preserved), PUBLIC_FILE_MODE)
        give_to_invoker(env_path)
    except OSError as exc:
        raise ComposeError(f"cannot write {env_path}: {exc.strerror}; run with sudo?") from exc
    return env_path


def stale_services(all_services: str, active_services: str) -> list[str]:
    """Services of profiles that are no longer active (``config --services`` with and without
    ``--profile '*'``). ``up --remove-orphans`` leaves their containers alone: Compose treats a
    disabled service as known, not as an orphan."""
    active = {line.strip() for line in active_services.splitlines() if line.strip()}
    every = {line.strip() for line in all_services.splitlines() if line.strip()}
    return sorted(every - active)


def parse_ps(output: str) -> list[ServiceStatus]:
    """``docker compose ps --format json``: one JSON object per line, or one JSON array."""
    text = output.strip()
    if not text:
        return []
    try:
        loaded = json.loads(text)
        records = loaded if isinstance(loaded, list) else [loaded]
    except json.JSONDecodeError:
        try:
            records = [json.loads(line) for line in text.splitlines() if line.strip()]
        except json.JSONDecodeError:
            raise ComposeError(f"unexpected `docker compose ps` output: {text[:200]!r}") from None
    if not all(isinstance(record, dict) for record in records):
        raise ComposeError(f"unexpected `docker compose ps` output: {text[:200]!r}")
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
        version = probe.stdout.strip()
        if engine_too_old(version):
            floor = ".".join(str(part) for part in MIN_DOCKER_ENGINE)
            raise ComposeError(
                f"Docker Engine {version} is older than {floor}: ports published on 127.0.0.1"
                " are reachable from the LAN on such versions",
                "remove the distro Docker (apt-get purge docker.io docker-compose) and re-run"
                " install.sh to get docker-ce from download.docker.com",
            )
        return
    # Match the dial error, which is the same across CLI versions, not the surrounding prose
    # (Docker 29 says "failed to connect to the docker API", older ones "Cannot connect").
    stderr = probe.stderr.strip().lower()
    if "permission denied" in stderr:
        raise ComposeError(
            "no access to the Docker socket: log out and in again after install.sh added you"
            " to the docker group, or run with sudo"
        )
    if "no such file or directory" in stderr or "connection refused" in stderr:
        raise ComposeError("the Docker daemon is not running: sudo systemctl start docker")
    raise ComposeError(f"docker is not usable: {probe.stderr.strip()}")


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
