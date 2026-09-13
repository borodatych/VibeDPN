"""hostapd of gateway mode: the Wi-Fi access point on the LAN interface, rendered by core.

Rendered like dnsmasq.conf at every start of core (docs/decisions.md, decision 10). The passphrase
lives in secrets/wifi-passphrase, not in config.yaml, so the rendered file is written mode 600.
Keys: docs/knowledge/linux/hostapdConfigCheck.md.
"""

from __future__ import annotations

import os
from pathlib import Path

from vibedpn.atomic import write_private
from vibedpn.config import Config, NetworkMode, WifiBand, WifiSecurity

CONF_FILE = "hostapd.conf"
PASSPHRASE_FILE = "wifi-passphrase"
DIR_ENV = "VIBEDPN_HOSTAPD_CONF"
DEFAULT_DIR = Path("/etc/vibedpn/hostapd")  # compose.yaml mounts ./data/hostapd there
HW_MODES = {WifiBand.BAND_2_4: "g", WifiBand.BAND_5: "a"}
# WPA2/WPA3 transition keeps devices without SAE; wpa3 is SAE only with mandatory frame protection
KEY_MGMT = {WifiSecurity.WPA2_WPA3: "WPA-PSK SAE", WifiSecurity.WPA3: "SAE"}
FRAME_PROTECTION = {WifiSecurity.WPA2_WPA3: 1, WifiSecurity.WPA3: 2}
# hash-to-element or hunting-and-pecking, whichever the device supports
SAE_PWE_BOTH = 2


class HostapdError(RuntimeError):
    """A user-facing reason why the access point configuration could not be written."""


def core_dir() -> Path:
    return Path(os.environ.get(DIR_ENV, DEFAULT_DIR))


def hostapd_conf(config: Config, passphrase: str) -> str | None:
    """The configuration of a gateway box with Wi-Fi, ``None`` for any other."""
    network = config.network
    if network is None or network.mode is not NetworkMode.GATEWAY or network.wifi is None:
        return None
    wifi = network.wifi
    lines = [
        "# Rendered by vibedpn core from config.yaml and secrets/wifi-passphrase at every start.",
        f"interface={network.lan_interface}",
        "driver=nl80211",
        f"ssid={wifi.ssid}",
        f"country_code={wifi.country}",
        f"hw_mode={HW_MODES[wifi.band]}",
        f"channel={wifi.channel}",
        "wpa=2",
        f"wpa_key_mgmt={KEY_MGMT[wifi.security]}",
        "rsn_pairwise=CCMP",
        f"ieee80211w={FRAME_PROTECTION[wifi.security]}",
        f"sae_pwe={SAE_PWE_BOTH}",
        f"wpa_passphrase={passphrase}",
    ]
    return "\n".join(lines) + "\n"


def read_passphrase(secrets_dir: Path) -> str:
    path = secrets_dir / PASSPHRASE_FILE
    try:
        passphrase = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        raise HostapdError(
            f"{path} is missing: run `sudo vibedpn init --force` to generate the Wi-Fi passphrase"
        ) from None
    except OSError as exc:
        raise HostapdError(f"cannot read {path}: {exc.strerror or exc}") from exc
    if not passphrase:
        raise HostapdError(f"{path} is empty")
    return passphrase


def ensure_hostapd(config: Config, conf_dir: Path, secrets_dir: Path) -> bool | None:
    """Write ``hostapd.conf``; ``None`` on a box without Wi-Fi, else whether it changed."""
    network = config.network
    if network is None or network.wifi is None:
        return None
    text = hostapd_conf(config, read_passphrase(secrets_dir))
    if text is None:
        return None
    try:
        conf_dir.mkdir(parents=True, exist_ok=True)
        return write_private(conf_dir / CONF_FILE, text)
    except OSError as exc:
        raise HostapdError(f"cannot write {conf_dir / CONF_FILE}: {exc.strerror or exc}") from exc
