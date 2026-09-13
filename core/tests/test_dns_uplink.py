"""AdGuard upstream queries through the uplink of routing.mode full (decision 14)."""

from pathlib import Path

from ruamel.yaml import YAML

from vibedpn.config import Config
from vibedpn.engine.adguard import give_to_adguard
from vibedpn.engine.router import ADGUARD_UID, router_ruleset

from .conftest import client_config

COMPOSE = Path(__file__).resolve().parents[2] / "compose.yaml"


def ruleset(mode: str, *, dns: bool = True) -> str:
    raw = client_config()
    raw["routing"]["mode"] = mode
    raw["dns"] = {"enabled": dns}
    text = router_ruleset(Config.model_validate(raw))
    assert text is not None
    return text


def test_full_mode_steers_the_adguard_user_but_not_its_answers() -> None:
    text = ruleset("full")
    assert "type route hook output priority mangle" in text
    assert f"meta skuid != {ADGUARD_UID} return" in text
    assert "ip daddr 192.168.1.0/24 return" in text and "fib daddr type local return" in text
    assert "meta mark set 0x10" in text.split("chain dns_uplink")[1]
    assert f"meta skuid {ADGUARD_UID} meta nfproto ipv6" in text


def test_off_mode_or_no_adguard_leaves_dns_direct() -> None:
    assert "dns_uplink" not in ruleset("off")
    assert "dns_uplink" not in ruleset("full", dns=False)
    assert "meta skuid" not in ruleset("off")


def test_compose_runs_adguard_as_that_user() -> None:
    service = YAML(typ="safe").load(COMPOSE.read_text(encoding="utf-8"))["services"]["adguard"]
    assert service["user"] == f"{ADGUARD_UID}:{ADGUARD_UID}"
    assert service["cap_add"] == ["NET_BIND_SERVICE"]


def test_the_directories_of_adguard_change_owner_once(tmp_path: Path) -> None:
    conf = tmp_path / "conf"
    work = tmp_path / "work" / "data"
    work.mkdir(parents=True)
    (conf).mkdir()
    (conf / "AdGuardHome.yaml").write_text("x", encoding="utf-8")
    owners: dict[Path, tuple[int, int]] = {}

    def chown(path: Path, uid: int, gid: int) -> None:
        owners[path] = (uid, gid)

    changed = give_to_adguard([conf, tmp_path / "work"], ADGUARD_UID, chown)
    assert changed == 4  # conf, its file, work, work/data
    assert set(owners.values()) == {(ADGUARD_UID, ADGUARD_UID)}
