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
# An ASCII passphrase of WPA-PSK is 8..63 characters (docs/knowledge/linux/hostapdConfigCheck.md).
PASSPHRASE_MIN = 8
PASSPHRASE_MAX = 63
PRINTABLE_FIRST = 0x20
PRINTABLE_LAST = 0x7E
DIR_ENV = "VIBEDPN_HOSTAPD_CONF"
DEFAULT_DIR = Path("/etc/vibedpn/hostapd")  # compose.yaml mounts ./data/hostapd there
HW_MODES = {WifiBand.BAND_2_4: "g", WifiBand.BAND_5: "a"}
# WPA2/WPA3 transition keeps devices without SAE; wpa3 is SAE only with mandatory frame protection
KEY_MGMT = {WifiSecurity.WPA2_WPA3: "WPA-PSK SAE", WifiSecurity.WPA3: "SAE"}
FRAME_PROTECTION = {WifiSecurity.WPA2_WPA3: 1, WifiSecurity.WPA3: 2}
# hash-to-element or hunting-and-pecking, whichever the device supports
SAE_PWE_BOTH = 2
# RTL8852BE (rtw89) on the N100 box kicked a phone every few seconds as a legacy 802.11g AP that
# drops stations on low ack; 802.11n with WMM and no low-ack kick made that minutes, not seconds
# (docs/knowledge/linux/hostapdConfigCheck.md).
STABLE_AP_LINES = ("ieee80211n=1", "wmm_enabled=1", "disassoc_low_ack=0")


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
        *STABLE_AP_LINES,
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


def check_passphrase(value: str) -> str:
    """A passphrase devices can type and hostapd accepts; raise ``HostapdError`` with the reason."""
    if not PASSPHRASE_MIN <= len(value) <= PASSPHRASE_MAX:
        raise HostapdError(
            f"the Wi-Fi passphrase is {PASSPHRASE_MIN} to {PASSPHRASE_MAX} characters,"
            f" not {len(value)}"
        )
    if any(not PRINTABLE_FIRST <= ord(char) <= PRINTABLE_LAST for char in value):
        raise HostapdError(
            "the Wi-Fi passphrase takes Latin letters, digits, spaces and punctuation only"
        )
    if value != value.strip():
        raise HostapdError("the Wi-Fi passphrase cannot start or end with a space")
    return value


def write_passphrase(secrets_dir: Path, value: str) -> bool:
    """Store the passphrase in secrets/ (mode 600); whether it changed."""
    path = secrets_dir / PASSPHRASE_FILE
    try:
        return write_private(path, check_passphrase(value))
    except OSError as exc:
        raise HostapdError(f"cannot write {path}: {exc.strerror or exc}; run with sudo?") from exc


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
