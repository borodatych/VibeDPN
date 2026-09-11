"""Shipped examples must always validate: config.example.yaml and the YAML blocks of the spec."""

import re
from pathlib import Path

import pytest

from vibedpn.config import Config, Profile, load_config, parse_yaml

REPO_ROOT = Path(__file__).resolve().parents[2]  # tests/ -> core/ -> repository root
EXAMPLE = REPO_ROOT / "config.example.yaml"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
SPEC = REPO_ROOT / "docs" / "manuals" / "configSpec.md"
YAML_BLOCK = re.compile(r"```yaml\n(# example: .*?)```", re.DOTALL)


def test_config_example_is_a_valid_home_box() -> None:
    config = load_config(EXAMPLE)
    assert config.role.value == "home"
    assert config.compose_profiles() == [
        Profile.PROVIDER,
        Profile.CONSUMER,
        Profile.ROUTER,
        Profile.DNS,
        Profile.UI,
    ]


def test_env_example_matches_config_example() -> None:
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    assignments = {line.split("=", 1)[0]: line.split("=", 1)[1] for line in lines if "=" in line}
    derived = load_config(EXAMPLE).env_vars()
    assert {k: assignments.get(k) for k in derived} == derived
    assert set(assignments) - set(derived) == {"VIBEDPN_TAG"}


def spec_examples() -> list[str]:
    return YAML_BLOCK.findall(SPEC.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "block", spec_examples(), ids=lambda b: b.splitlines()[0].removeprefix("# example: ")
)
def test_spec_examples_validate(block: str) -> None:
    Config.model_validate(parse_yaml(block))


def test_spec_has_an_example_per_role() -> None:
    roles = {Config.model_validate(parse_yaml(block)).role.value for block in spec_examples()}
    assert roles == {"home", "vps", "client"}
