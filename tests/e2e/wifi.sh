#!/bin/sh
# E2E stand of the Wi-Fi access point of gateway mode on virtual radios (mac80211_hwsim): a device
# joins the network of the box with the passphrase init generated, gets its address over DHCP and
# leaves through the NAT of the box.
#
# What runs is the product: `vibedpn init --lan-interface --wifi-ssid --wifi-country`, `up`,
# `wifi show`, `doctor`, the core, dnsmasq and hostapd images of the repository. The box is a lean
# role home (core, dnsmasq, hostapd). The first radio stays with the host as the LAN of the box, with
# the address the stand sets as the OS would; the second radio moves into a namespace as the device,
# which joins with WPA3-SAE the access point that also admits WPA2 devices.
#
# Needs: Linux with the mac80211_hwsim module (Ubuntu: linux-modules-extra-$(uname -r)), Docker
# Engine >= 28, sudo, curl, iw, wpa_supplicant, dhcpcd, python3 (or VIBEDPN_E2E_PYTHON), the
# internet, images ghcr.io/borodatych/vibedpn-{core,dnsmasq,hostapd}:$TAG.
# The stand reloads mac80211_hwsim: virtual radios of anything else on the host disappear.
set -eu
# iw, wpa_supplicant and dhcpcd live in sbin, which Debian keeps off the PATH of an ordinary user
PATH="$PATH:/usr/local/sbin:/usr/sbin:/sbin"
export PATH

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
TAG="${VIBEDPN_TAG:-e2e}"
CORE_IMAGE="ghcr.io/borodatych/vibedpn-core:$TAG"
DNSMASQ_IMAGE="ghcr.io/borodatych/vibedpn-dnsmasq:$TAG"
HOSTAPD_IMAGE="ghcr.io/borodatych/vibedpn-hostapd:$TAG"
EXIT_URL="${VIBEDPN_E2E_EXIT_URL:-https://api.ipify.org}"
WORK="$(mktemp -d)"
BOX="$WORK/box"
PASSWORD=e2e-wifi-123
LAN_SUBNET=192.168.79.0/24
BOX_LAN_IP=192.168.79.1
NETNS=e2e-wifista
SSID=vibedpn-e2e
COUNTRY=DE
TIMEOUT=180

log() {
  echo "== $*"
}

cleanup() {
  if [ -f "$WORK/wpa.pid" ]; then
    sudo kill "$(sudo cat "$WORK/wpa.pid")" 2>/dev/null || true
  fi
  if [ -n "${STA_IF:-}" ]; then
    sudo ip netns exec "$NETNS" dhcpcd -x "$STA_IF" >/dev/null 2>&1 || true
  fi
  if [ -n "${CLI:-}" ] && [ -f "$BOX/config.yaml" ]; then
    sudo "$CLI" down --dir "$BOX" >/dev/null 2>&1 || true
  fi
  if [ -n "${PY:-}" ] && [ -x "$PY" ]; then
    sudo "$PY" -c "from vibedpn.engine.router import remove_router; remove_router()" >/dev/null 2>&1 || true
  fi
  sudo ip netns del "$NETNS" 2>/dev/null || true
  if [ "${LOADED_HWSIM:-0}" = 1 ]; then
    sudo modprobe -r mac80211_hwsim 2>/dev/null || true
  fi
  sudo rm -rf "$WORK" "/etc/netns/$NETNS"
}
trap cleanup EXIT

fail() {
  echo "FAIL: $*" >&2
  {
    echo "--- diagnostics"
    echo "# containers"; docker ps -a --filter name=vibedpn- --format '{{.Names}} {{.Status}}'
    echo "# core"; docker logs --tail 25 vibedpn-core-1
    echo "# hostapd"; docker logs --tail 25 vibedpn-hostapd-1
    echo "# dnsmasq"; docker logs --tail 15 vibedpn-dnsmasq-1
    echo "# station"; sudo tail -n 15 "$WORK/wpa.log"
  } >&2 2>&1 || true
  exit 1
}

# --- the CLI ------------------------------------------------------------------------------------
if [ -n "${VIBEDPN_E2E_PYTHON:-}" ]; then
  PY="$VIBEDPN_E2E_PYTHON"
else
  python3 -m venv "$WORK/venv"
  "$WORK/venv/bin/pip" install -q --require-hashes -r "$REPO/core/requirements.txt"
  "$WORK/venv/bin/pip" install -q --no-deps "$REPO/core"
  PY="$WORK/venv/bin/python"
fi
CLI="$(dirname "$PY")/vibedpn"
[ -x "$CLI" ] || fail "no vibedpn next to $PY"
docker image inspect "$CORE_IMAGE" "$DNSMASQ_IMAGE" "$HOSTAPD_IMAGE" >/dev/null 2>&1 ||
  fail "build $CORE_IMAGE, $DNSMASQ_IMAGE and $HOSTAPD_IMAGE first (core, images/dnsmasq, images/hostapd)"
for tool in iw wpa_supplicant dhcpcd; do
  command -v "$tool" >/dev/null || fail "$tool is needed for the device side of the stand"
done
modinfo mac80211_hwsim >/dev/null 2>&1 ||
  fail "no mac80211_hwsim module: install linux-modules-extra-$(uname -r)"

# --- the radios ---------------------------------------------------------------------------------
log "stand: two virtual radios, one for the box and one for the device"
sudo modprobe -r mac80211_hwsim 2>/dev/null || true
sudo modprobe mac80211_hwsim radios=2
LOADED_HWSIM=1
AP_IF=""
STA_IF=""
STA_PHY=""
i=0
while [ -z "$STA_IF" ]; do
  for dev in /sys/class/net/*; do
    [ -e "$dev/phy80211" ] || continue
    if [ -z "$AP_IF" ]; then
      AP_IF="$(basename "$dev")"
    elif [ "$(basename "$dev")" != "$AP_IF" ]; then
      STA_IF="$(basename "$dev")"
      STA_PHY="$(basename "$(readlink "$dev/phy80211")")"
    fi
  done
  i=$((i + 1))
  [ "$i" -lt 10 ] || fail "mac80211_hwsim radios=2 did not create two wireless interfaces"
  [ -n "$STA_IF" ] || sleep 1
done
echo "box radio $AP_IF, device radio $STA_IF ($STA_PHY)"
sudo ip addr add "$BOX_LAN_IP/24" dev "$AP_IF"
sudo ip link set "$AP_IF" up
sudo ip netns add "$NETNS"
# dhcpcd in the namespace must not rewrite the resolv.conf of the host (see gateway.sh)
sudo mkdir -p "/etc/netns/$NETNS"
sudo touch "/etc/netns/$NETNS/resolv.conf"
sudo iw phy "$STA_PHY" set netns name "$NETNS"
sudo ip netns exec "$NETNS" ip link set lo up
sudo ip netns exec "$NETNS" ip link set "$STA_IF" up
DEVICE_MAC="$(sudo ip netns exec "$NETNS" cat "/sys/class/net/$STA_IF/address")"
WAN="$(ip route show default | awk 'NR == 1 { print $5 }')"
[ -n "$WAN" ] || fail "the host has no default route"

# --- the box ------------------------------------------------------------------------------------
log "box: gateway mode, WAN $WAN, Wi-Fi '$SSID' on $AP_IF"
mkdir "$BOX"
cp "$REPO/compose.yaml" "$BOX/"
printf '%s\n' "$PASSWORD" >"$WORK/password"
init_out="$(sudo "$CLI" init --dir "$BOX" --role home --ui-variant full --lan-interface "$AP_IF" \
  --wifi-ssid "$SSID" --wifi-country "$COUNTRY" --password-file "$WORK/password" 2>&1)" ||
  fail "init with Wi-Fi failed: $init_out"
printf '%s\n' "$init_out" | grep -q "^Wi-Fi '$SSID'" || fail "init did not announce the access point: $init_out"
sudo test -s "$BOX/secrets/wifi-passphrase" || fail "init did not generate secrets/wifi-passphrase"
# the stand keeps only core, dnsmasq and hostapd: the checks below are about Wi-Fi, DHCP and NAT
sudo "$PY" - "$BOX/config.yaml" <<'PY'
import sys
from pathlib import Path

from vibedpn.bootstrap import render_config
from vibedpn.config import Config, load_config

path = Path(sys.argv[1])
raw = load_config(path).model_dump(mode="json", exclude_none=True, exclude={"firewall"})
raw["provider"]["enabled"] = False
raw["dns"]["enabled"] = False
raw["ui"]["enabled"] = False
raw["upstreams"]["dpn"]["enabled"] = False
path.write_text(render_config(Config.model_validate(raw)), encoding="utf-8")
PY
sudo sed -i "s/^VIBEDPN_TAG=.*/VIBEDPN_TAG=$TAG/" "$BOX/.env"
sudo "$CLI" up --dir "$BOX" >/dev/null 2>&1 || fail "vibedpn up failed"
grep -q "^COMPOSE_PROFILES=router,dhcp,wifi$" "$BOX/.env" || fail "network.wifi did not enable the profile wifi"

log "core, dnsmasq and the access point come up"
settled() {
  for name in core dnsmasq hostapd; do
    status="$(docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' "vibedpn-$name-1" 2>/dev/null || echo missing)"
    case "$status" in
      "running "|"running healthy") ;;
      *) return 1 ;;
    esac
  done
  docker logs vibedpn-hostapd-1 2>&1 | grep -q "AP-ENABLED"
}
i=0
until settled; do
  i=$((i + 5))
  [ "$i" -lt "$TIMEOUT" ] || fail "core, dnsmasq and an enabled access point did not come up in $TIMEOUT s"
  sleep 5
done
[ "$(sudo stat -c %a "$BOX/data/hostapd/hostapd.conf")" = 600 ] ||
  fail "hostapd.conf with the passphrase is not mode 600"
echo "access point enabled on $AP_IF"

log "the device joins with the passphrase from vibedpn wifi show"
wifi_out="$(sudo "$CLI" wifi show --dir "$BOX")" || fail "vibedpn wifi show failed"
printf '%s\n' "$wifi_out" | grep -q "^ssid: $SSID$" || fail "wifi show names another network"
passphrase="$(printf '%s\n' "$wifi_out" | sed -n 's/^passphrase: //p')"
[ -n "$passphrase" ] || fail "wifi show printed no passphrase"
(
  umask 077
  printf 'sae_pwe=2\nnetwork={\n ssid="%s"\n key_mgmt=SAE\n ieee80211w=2\n sae_password="%s"\n}\n' \
    "$SSID" "$passphrase" >"$WORK/station.conf"
)
sudo ip netns exec "$NETNS" wpa_supplicant -B -D nl80211 -i "$STA_IF" -c "$WORK/station.conf" \
  -P "$WORK/wpa.pid" -f "$WORK/wpa.log" || fail "wpa_supplicant did not start"
i=0
until docker logs vibedpn-hostapd-1 2>&1 | grep -q "EAPOL-4WAY-HS-COMPLETED $DEVICE_MAC"; do
  i=$((i + 2))
  [ "$i" -lt 60 ] || fail "the device $DEVICE_MAC did not complete WPA3-SAE with the access point"
  sleep 2
done
echo "device $DEVICE_MAC joined '$SSID' with SAE"

log "the device gets an address from the box over Wi-Fi"
sudo ip netns exec "$NETNS" dhcpcd --oneshot --ipv4only --nohook resolv.conf --timeout 60 "$STA_IF" >/dev/null 2>&1 ||
  fail "the device got no DHCP lease over Wi-Fi"
device_ip="$(sudo ip netns exec "$NETNS" ip -4 -o addr show dev "$STA_IF" | awk '{ split($4, a, "/"); print a[1] }')"
gateway="$(sudo ip netns exec "$NETNS" ip route show default | awk 'NR == 1 { print $3 }')"
[ "$gateway" = "$BOX_LAN_IP" ] || fail "the device's gateway is '${gateway:-none}', not the box $BOX_LAN_IP"
sudo grep -q " $DEVICE_MAC $device_ip " "$BOX/data/dnsmasq/leases" ||
  fail "data/dnsmasq/leases has no lease of $DEVICE_MAC at ${device_ip:-none}"
echo "device $device_ip via $gateway"

log "the device reaches the internet through the NAT of the box"
sudo nft list table inet vibedpn_router | grep -q "oifname \"$WAN\" ip saddr $LAN_SUBNET masquerade" ||
  fail "the router has no masquerade of the LAN out of $WAN"
host_exit="$(curl -s --max-time 15 "$EXIT_URL" || true)"
[ -n "$host_exit" ] || fail "the host itself gets no answer from $EXIT_URL"
exit_host="$(printf '%s' "$EXIT_URL" | sed -E 's#^[a-z]+://([^/:]+).*#\1#')"
exit_ip="$(getent ahostsv4 "$exit_host" | awk 'NR == 1 { print $1 }')"
device_exit="$(sudo ip netns exec "$NETNS" curl -s --max-time 15 --resolve "$exit_host:443:$exit_ip" "$EXIT_URL" || true)"
[ "$device_exit" = "$host_exit" ] || fail "the device leaves as '${device_exit:-nothing}', the box as $host_exit"
echo "the device leaves as the box"

log "doctor"
report="$(sudo "$CLI" doctor --dir "$BOX" || true)"
printf '%s\n' "$report" | grep -q "\[ ok \] wifi" || fail "doctor does not confirm the access point: $report"
printf '%s\n' "$report" | grep -q "\[ ok \] lan address" || fail "doctor does not confirm the LAN address: $report"

log "wifi stand passed"
