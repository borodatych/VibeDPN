"""The Wi-Fi passphrase set from the panel: core stores it, renders hostapd.conf and has the running
hostapd read it again (RELOAD_CONFIG); no container is recreated."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vibedpn.api.app import create_app
from vibedpn.api.models import WifiPassphraseView
from vibedpn.config import Config
from vibedpn.engine.hostapd import CONF_FILE, PASSPHRASE_FILE, write_passphrase
from vibedpn.engine.wifi import HostapdControl, WifiError

from .conftest import vps_config
from .test_events import FakeHostapd, short_dir  # noqa: F401 — a fixture
from .test_wifi import wifi_box

OLD = "old home wifi 1"
NEW = "new home wifi 2"


class ReloadingHostapd(FakeHostapd):
    """hostapd that also answers RELOAD_CONFIG, with OK or FAIL."""

    reply = "OK\n"

    def _reply(self, command: str) -> str:
        if command == "RELOAD_CONFIG":
            return self.reply
        return super()._reply(command)


def test_the_control_socket_reloads_or_says_it_could_not(short_dir: Path) -> None:  # noqa: F811
    hostapd = ReloadingHostapd(short_dir, [])
    try:
        with HostapdControl("wlan0", short_dir) as control:
            control.reload_config()
            hostapd.reply = "FAIL\n"
            with pytest.raises(WifiError, match="could not read its configuration again"):
                control.reload_config()
    finally:
        hostapd.close()


def box_app(tmp_path: Path, reload: object) -> tuple[TestClient, Path, Path]:
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    write_passphrase(secrets, OLD)
    conf_dir = tmp_path / "hostapd"
    app = create_app(
        Config.model_validate(wifi_box()),
        secrets_dir=secrets,
        hostapd_dir=conf_dir,
        wifi_reload=reload,  # type: ignore[arg-type]
    )
    return TestClient(app), secrets / PASSPHRASE_FILE, conf_dir / CONF_FILE


def test_a_new_passphrase_is_stored_rendered_and_reloaded(tmp_path: Path) -> None:
    reloaded: list[str] = []
    client, secret, conf = box_app(tmp_path, reloaded.append)
    answer = client.put("/wifi/passphrase", json={"passphrase": NEW})
    assert answer.status_code == 200 and answer.json() == {"result": "applied", "error": ""}
    assert secret.read_text(encoding="utf-8") == NEW
    assert f"wpa_passphrase={NEW}\n" in conf.read_text(encoding="utf-8")
    assert conf.stat().st_mode & 0o777 == 0o600
    assert reloaded == ["wlan0"]
    again = client.put("/wifi/passphrase", json={"passphrase": NEW})
    assert again.json()["result"] == "unchanged" and reloaded == ["wlan0"]  # nobody dropped


def test_a_passphrase_hostapd_would_refuse_changes_nothing(tmp_path: Path) -> None:
    reloaded: list[str] = []
    client, secret, conf = box_app(tmp_path, reloaded.append)
    answer = client.put("/wifi/passphrase", json={"passphrase": "short"})
    assert answer.status_code == 422 and "8 to 63 characters" in answer.json()["detail"]
    assert "short" not in answer.json()["detail"]  # the reason, never the value
    assert secret.read_text(encoding="utf-8") == OLD and not conf.exists() and reloaded == []


def test_a_silent_access_point_takes_the_passphrase_at_its_start(tmp_path: Path) -> None:
    def silent(_interface: str) -> None:
        raise WifiError("cannot reach the access point at /run/vibedpn/hostapd/wlan0")

    client, secret, conf = box_app(tmp_path, silent)
    answer = WifiPassphraseView.model_validate(
        client.put("/wifi/passphrase", json={"passphrase": NEW}).json()
    )
    assert answer.result == "pending" and "cannot reach" in answer.error
    assert secret.read_text(encoding="utf-8") == NEW
    assert f"wpa_passphrase={NEW}\n" in conf.read_text(encoding="utf-8")


def test_a_box_without_an_access_point_has_no_passphrase(tmp_path: Path) -> None:
    client = TestClient(create_app(Config.model_validate(vps_config()), secrets_dir=tmp_path))
    assert client.put("/wifi/passphrase", json={"passphrase": NEW}).status_code == 404
