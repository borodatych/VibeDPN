#!/bin/sh
# E2E stand of gateway mode: the box is the router of its LAN — it hands the device an address over
# DHCP (dnsmasq) and NATs the device out of its WAN interface.
#
# What runs is the product: `vibedpn init`, `up`, `doctor`, the core and dnsmasq images of the
# repository. The box is a lean role home (no node, no uplink, no DNS, no panel): only core and
# dnsmasq, so the stand checks DHCP and NAT and nothing else. LAN: a bridge lan0 whose address the
# stand sets itself, as the OS does on a real box. WAN: the default interface of the host. Unlike the
# home stand there is no emulated ISP NAT: a device that reaches the internet got there through the
# box.
#
# Needs: Linux, Docker Engine >= 28, sudo, curl, dhcpcd, python3 (or VIBEDPN_E2E_PYTHON), the
# internet, images ghcr.io/borodatych/vibedpn-core:$TAG and ghcr.io/borodatych/vibedpn-dnsmasq:$TAG.
set -eu

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
TAG="${VIBEDPN_TAG:-e2e}"
CORE_IMAGE="ghcr.io/borodatych/vibedpn-core:$TAG"
DNSMASQ_IMAGE="ghcr.io/borodatych/vibedpn-dnsmasq:$TAG"
EXIT_URL="${VIBEDPN_E2E_EXIT_URL:-https://api.ipify.org}"
WORK="$(mktemp -d)"
BOX="$WORK/box"
PASSWORD=e2e-gateway-123
LAN=lan0
LAN_SUBNET=192.168.78.0/24
BOX_LAN_IP=192.168.78.1
POOL_START=192.168.78.100
POOL_END=192.168.78.120
NETNS=e2e-gwlan
DEVICE_IF=e2e-gdev
TIMEOUT=180

log() {
  echo "== $*"
}

cleanup() {
  if [ -n "${NETNS_PID:-}" ]; then
    sudo ip netns exec "$NETNS" dhcpcd -x "$DEVICE_IF" >/dev/null 2>&1 || true
  fi
  if [ -n "${CLI:-}" ] && [ -f "$BOX/config.yaml" ]; then
    sudo "$CLI" down --dir "$BOX" >/dev/null 2>&1 || true
  fi
  if [ -n "${PY:-}" ] && [ -x "$PY" ]; then
    sudo "$PY" -c "from vibedpn.engine.router import remove_router; remove_router()" >/dev/null 2>&1 || true
  fi
  sudo ip netns del "$NETNS" 2>/dev/null || true
  sudo ip link del "$LAN" 2>/dev/null || true
  sudo rm -rf "$WORK" "/etc/netns/$NETNS"
}
trap cleanup EXIT

fail() {
  echo "FAIL: $*" >&2
  {
    echo "--- diagnostics"
    echo "# containers"; docker ps -a --filter name=vibedpn- --format '{{.Names}} {{.Status}}'
    echo "# core"; docker logs --tail 25 vibedpn-core-1
    echo "# dnsmasq"; docker logs --tail 25 vibedpn-dnsmasq-1
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
docker image inspect "$CORE_IMAGE" "$DNSMASQ_IMAGE" >/dev/null 2>&1 ||
  fail "build $CORE_IMAGE and $DNSMASQ_IMAGE first (core, images/dnsmasq)"
command -v dhcpcd >/dev/null || fail "dhcpcd is needed for the device's DHCP client"

# --- the LAN ------------------------------------------------------------------------------------
log "stand: the LAN bridge with the box address and a device without one"
WAN="$(ip route show default | awk 'NR == 1 { print $5 }')"
[ -n "$WAN" ] || fail "the host has no default route"
sudo ip link add "$LAN" type bridge
sudo ip addr add "$BOX_LAN_IP/24" dev "$LAN"
sudo ip link set "$LAN" up
sudo ip netns add "$NETNS"
# dhcpcd in the namespace must not rewrite the resolv.conf of the host: `ip netns exec` bind-mounts
# /etc/netns/<name>/ files over /etc, so the namespace gets its own copy.
sudo mkdir -p "/etc/netns/$NETNS"
sudo touch "/etc/netns/$NETNS/resolv.conf"
sudo ip link add "$DEVICE_IF" type veth peer name e2e-glan
sudo ip link set e2e-glan master "$LAN" up
sudo ip link set "$DEVICE_IF" netns "$NETNS"
sudo ip netns exec "$NETNS" ip link set "$DEVICE_IF" up
sudo ip netns exec "$NETNS" ip link set lo up
DEVICE_MAC="$(sudo ip netns exec "$NETNS" cat "/sys/class/net/$DEVICE_IF/address")"

# --- the box ------------------------------------------------------------------------------------
log "box: gateway mode, WAN $WAN, LAN $LAN, pool $POOL_START-$POOL_END"
mkdir "$BOX"
cp "$REPO/compose.yaml" "$BOX/"
printf '%s\n' "$PASSWORD" >"$WORK/password"
sudo "$CLI" init --dir "$BOX" --role home --ui-variant full --password-file "$WORK/password" >/dev/null
sudo "$PY" - "$BOX/config.yaml" "$LAN" "$LAN_SUBNET" "$BOX_LAN_IP" "$WAN" "$POOL_START" "$POOL_END" <<'PY'
import sys
from pathlib import Path

from vibedpn.bootstrap import render_config
from vibedpn.config import Config

path, lan, subnet, address, wan, start, end = sys.argv[1:]
raw = {
    "version": 1,
    "role": "home",
    "network": {
        "mode": "gateway",
        "lan_interface": lan,
        "lan_subnet": subnet,
        "lan_address": address,
        "wan_interface": wan,
        "dhcp": {"range_start": start, "range_end": end, "lease": "1h"},
    },
    "routing": {"mode": "off", "default_upstream": "dpn"},
    "upstreams": {"dpn": {"enabled": False}},
    "provider": {"enabled": False},
    "dns": {"enabled": False},
    "ui": {"enabled": False},
}
Path(path).write_text(render_config(Config.model_validate(raw)), encoding="utf-8")
PY
sudo sed -i "s/^VIBEDPN_TAG=.*/VIBEDPN_TAG=$TAG/" "$BOX/.env"
sudo "$CLI" up --dir "$BOX" >/dev/null 2>&1 || fail "vibedpn up failed"
grep -q "^COMPOSE_PROFILES=router,dhcp$" "$BOX/.env" || fail "gateway mode did not enable the profile dhcp"

log "core and dnsmasq come up"
settled() {
  for name in core dnsmasq; do
    status="$(docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' "vibedpn-$name-1" 2>/dev/null || echo missing)"
    case "$status" in
      "running "|"running healthy") ;;
      *) return 1 ;;
    esac
  done
}
i=0
until settled; do
  i=$((i + 5))
  [ "$i" -lt "$TIMEOUT" ] || fail "core and dnsmasq did not come up in $TIMEOUT s"
  sleep 5
done
sudo grep -q "^dhcp-range=$POOL_START,$POOL_END,1h$" "$BOX/data/dnsmasq/dnsmasq.conf" ||
  fail "core did not render the DHCP range into data/dnsmasq/dnsmasq.conf"

log "the device gets an address, the gateway and a lease from the box"
sudo ip netns exec "$NETNS" dhcpcd --oneshot --ipv4only --nohook resolv.conf --timeout 60 "$DEVICE_IF" >/dev/null 2>&1 ||
  fail "the device got no DHCP lease from the box"
NETNS_PID=1
device_ip="$(sudo ip netns exec "$NETNS" ip -4 -o addr show dev "$DEVICE_IF" | awk '{ split($4, a, "/"); print a[1] }')"
last="${device_ip##*.}"
[ -n "$device_ip" ] && [ "$last" -ge "${POOL_START##*.}" ] && [ "$last" -le "${POOL_END##*.}" ] ||
  fail "the device address '${device_ip:-none}' is outside the pool $POOL_START-$POOL_END"
gateway="$(sudo ip netns exec "$NETNS" ip route show default | awk 'NR == 1 { print $3 }')"
[ "$gateway" = "$BOX_LAN_IP" ] || fail "the device's default gateway is '${gateway:-none}', not the box $BOX_LAN_IP"
sudo grep -q " $DEVICE_MAC $device_ip " "$BOX/data/dnsmasq/leases" ||
  fail "data/dnsmasq/leases has no lease of $DEVICE_MAC at $device_ip"
echo "device $DEVICE_MAC: $device_ip via $gateway, lease recorded"

log "the device reaches the internet only through the NAT of the box"
sudo nft list table inet vibedpn_router | grep -q "oifname \"$WAN\" ip saddr $LAN_SUBNET masquerade" ||
  fail "the router has no masquerade of the LAN out of $WAN"
host_exit="$(curl -s --max-time 15 "$EXIT_URL" || true)"
[ -n "$host_exit" ] || fail "the host itself gets no answer from $EXIT_URL"
exit_host="$(printf '%s' "$EXIT_URL" | sed -E 's#^[a-z]+://([^/:]+).*#\1#')"
exit_ip="$(getent ahostsv4 "$exit_host" | awk 'NR == 1 { print $1 }')"
device_exit="$(sudo ip netns exec "$NETNS" curl -s --max-time 15 --resolve "$exit_host:443:$exit_ip" "$EXIT_URL" || true)"
[ "$device_exit" = "$host_exit" ] ||
  fail "the device leaves as '${device_exit:-nothing}', the box as $host_exit"
echo "the device leaves as the box: $host_exit"

log "doctor"
report="$(sudo "$CLI" doctor --dir "$BOX" || true)"
printf '%s\n' "$report" | grep -q "\[ ok \] lan address" || fail "doctor does not confirm the LAN address: $report"

log "gateway stand passed"
