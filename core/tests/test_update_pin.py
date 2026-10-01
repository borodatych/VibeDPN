"""An update moves the checkout and the images together: to the newest commit whose images CI has
published, with VIBEDPN_TAG pinned to that commit (engine/update.py, `vibedpn update`)"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from vibedpn import cli
from vibedpn.bootstrap import read_env, render_config
from vibedpn.compose import ComposeError
from vibedpn.config import Config
from vibedpn.doctor import Verdict, images_result
from vibedpn.engine.update import (
    commit_tag,
    managed_tag,
    pick_target,
    read_update_result,
    request_update,
    retag,
)

from .conftest import home_config

runner = CliRunner()
DATA = Path("data") / "core"
CURRENT = "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
BUILT = "2222222bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
BUILDING = "3333333ccccccccccccccccccccccccccccccccc"
IMAGES = ("ghcr.io/borodatych/vibedpn-core:next", "ghcr.io/borodatych/vibedpn-ui:next-full")


def test_the_newest_commit_with_all_its_images_is_the_target() -> None:
    ready = {BUILT}.__contains__
    chosen = pick_target([BUILDING, BUILT, CURRENT], CURRENT, ready)
    assert (chosen.commit, chosen.building) == (BUILT, BUILDING)
    nothing = pick_target([BUILDING, CURRENT], CURRENT, ready)
    assert (nothing.commit, nothing.building) == (None, BUILDING)
    # never back: a commit older than the box is not a target even with its images
    assert pick_target([CURRENT, BUILT], CURRENT, ready).commit is None


def test_the_tag_moves_with_its_variant_and_only_ours_is_pinned() -> None:
    assert commit_tag(BUILT) == "sha-2222222"
    assert (
        retag(IMAGES[1], "next", "sha-2222222") == "ghcr.io/borodatych/vibedpn-ui:sha-2222222-full"
    )
    assert retag("postgres:17.11-alpine", "next", "sha-2222222") == "postgres:17.11-alpine"
    assert managed_tag("next", "next") and managed_tag("sha-1111111", "next")
    assert not managed_tag("my-build", "next")


class Host:
    """A checkout of `next` at CURRENT; the registry has the images of BUILT, not of BUILDING"""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tag: str) -> None:
        self.commit = CURRENT
        self.calls: list[list[str]] = []
        self.ref: str | None = None
        self.silent_fetches = 0  # fetches that time out before one gets through
        monkeypatch.setattr(cli, "run", self.run)
        monkeypatch.setattr(cli, "capture", self.capture)
        monkeypatch.setattr(cli, "preflight", lambda: None)
        monkeypatch.setattr(cli, "checkout_image_tag", lambda _box: "next")
        (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
        config = Config.model_validate(home_config())
        (tmp_path / "config.yaml").write_text(render_config(config), encoding="utf-8")
        (tmp_path / ".env").write_text(
            f"COMPOSE_PROFILES=provider\nVIBEDPN_TAG={tag}\n", encoding="utf-8"
        )
        (tmp_path / "secrets").mkdir()
        (tmp_path / "secrets" / "htpasswd").write_text("admin:x\n", encoding="utf-8")
        (tmp_path / ".git").mkdir()
        (tmp_path / "install.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        (tmp_path / DATA).mkdir(parents=True)

    def run(self, argv: list[str]) -> int:
        self.calls.append(argv)
        if argv[-1].endswith("install.sh"):
            refs = [item.partition("=")[2] for item in argv if item.startswith("VIBEDPN_REF=")]
            self.ref = refs[0] if refs else None
            self.commit = self.ref or BUILDING  # without a ref install.sh takes the head
        return 0

    def capture(self, argv: list[str], *, timeout: float | None = None) -> str:
        self.calls.append(argv)
        if "fetch" in argv and self.silent_fetches > 0:
            self.silent_fetches -= 1
            raise ComposeError(f"git stayed silent for {timeout:g} s")
        if argv[:3] == ["docker", "manifest", "inspect"] and commit_tag(BUILT) not in argv[3]:
            raise ComposeError("manifest unknown")
        answers = {
            "rev-list": f"{BUILDING}\n{BUILT}\n{CURRENT}\n",
            "HEAD": f"{self.commit}\n",
            "--abbrev-ref": "next\n",
            "log": f"{self.commit[:7]} 2026-10-01T10:00:00+03:00\n",
            "--images": "\n".join([*IMAGES, "postgres:17.11-alpine"]) + "\n",
        }
        # the first word of the call that names it: `rev-parse --abbrev-ref HEAD` is the branch
        for word in ("rev-list", "--abbrev-ref", "HEAD", "log", "--images"):
            if word in argv:
                return answers[word]
        return ""


def update(tmp_path: Path) -> str:
    request_update(tmp_path / DATA, 100.0)
    result = runner.invoke(cli.app, ["update", "--requested", "--dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    done = read_update_result(tmp_path / DATA)
    assert done is not None and done.ok
    return done.message


def test_the_box_moves_to_the_commit_whose_images_are_out_and_pins_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = Host(tmp_path, monkeypatch, "next")
    message = update(tmp_path)
    assert host.ref == BUILT
    assert read_env(tmp_path / ".env")["VIBEDPN_TAG"] == "sha-2222222"
    assert "3333333 is newer, its images are still being built" in message
    done = read_update_result(tmp_path / DATA)
    assert done is not None and done.building == "3333333"  # a field for the panel, not a phrase
    manifests = [argv[3] for argv in host.calls if argv[:3] == ["docker", "manifest", "inspect"]]
    assert "ghcr.io/borodatych/vibedpn-ui:sha-2222222-full" in manifests
    assert not any(
        image.startswith("postgres") for image in manifests
    )  # upstream images are pinned


def test_a_tag_set_by_hand_is_left_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    host = Host(tmp_path, monkeypatch, "my-build")
    message = update(tmp_path)
    assert host.ref is None and read_env(tmp_path / ".env")["VIBEDPN_TAG"] == "my-build"
    assert "set by hand" in message


def test_the_doctor_tells_images_built_from_other_code_than_the_checkout() -> None:
    same = images_result(CURRENT, {IMAGES[0]: CURRENT, IMAGES[1]: CURRENT})
    assert same is not None and same.verdict is Verdict.OK
    behind = images_result(BUILT, {IMAGES[0]: BUILT, IMAGES[1]: CURRENT})
    assert behind is not None and behind.verdict is Verdict.WARN
    assert "vibedpn-ui:next-full (1111111)" in behind.detail and "vibedpn-core" not in behind.detail
    # an image built on the host carries no label: the owner's own, not judged
    assert images_result(CURRENT, {IMAGES[0]: ""}) is None
    assert images_result("", {IMAGES[0]: CURRENT}) is None


def test_a_silent_fetch_is_tried_again_and_a_dead_one_fails_the_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = Host(tmp_path, monkeypatch, "next")
    host.silent_fetches = 2  # a black-holed address twice, then a good one
    update(tmp_path)
    assert host.ref == BUILT
    host.silent_fetches = 3
    request_update(tmp_path / DATA, 200.0)
    failed = runner.invoke(cli.app, ["update", "--requested", "--dir", str(tmp_path)])
    assert failed.exit_code == 1
    done = read_update_result(tmp_path / DATA)
    assert done is not None and not done.ok and "cannot see what is new on next" in done.message
