#!/bin/sh
# E2E stand of uplink tor: a LAN device leaves through the box's Tor gateway, on one Linux host.
#
# What runs is the product itself: `vibedpn init/up/tor/upstream/mode/net/rule/doctor`, the core,
# wg-client and tor images of the repository, AdGuard Home. The box is role client (its uplink vps is
# a fake VPS, as in router.sh); uplink tor reaches the REAL Tor network, so this stand needs the
# internet and takes minutes, not seconds: a Snowflake bootstrap is slow.
#
# How "through Tor" is told from anything else: the LAN device has no way to the real internet of
# its own — its ISP path ends in the stand's fake internet (198.18.0.0/24). An answer from a public
# echo service therefore came through an uplink; the address it reports is compared with the
# host's own public address, which is what the fake VPS leaves with.
#
# Needs: Linux, Docker Engine >= 28, the wireguard module, sudo, curl, python3, the internet, images
# ghcr.io/borodatych/vibedpn-{core,wg,tor}:$VIBEDPN_TAG.
set -eu

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
TAG="${VIBEDPN_TAG:-e2e}"
WG_IMAGE="ghcr.io/borodatych/vibedpn-wg:$TAG"
CORE_IMAGE="ghcr.io/borodatych/vibedpn-core:$TAG"
TOR_IMAGE="ghcr.io/borodatych/vibedpn-tor:$TAG"
WORK="$(mktemp -d)"
BOX="$WORK/box"
PASSWORD=e2e-pass-123

INTERNET=e2e-internet
INTERNET_BRIDGE=e2einet0
INTERNET_SUBNET=198.18.0.0/24
INTERNET_GATEWAY=198.18.0.1
VPS=e2e-vps
VPS_IP=198.18.0.20
VPS_PORT=51899
LAN=lan0
LAN_SUBNET=192.168.77.0/24
BOX_LAN_IP=192.168.77.1
DEVICE_IP=192.168.77.2
NETNS=e2e-lanhost
ISP_COMMENT=e2e-isp
TIMEOUT=60
# Tor through Snowflake: minutes to bootstrap, seconds per circuit.
TOR_TIMEOUT=600
# A public echo of the caller's address; the stand only reads the answer.
ECHO_HOST=api.ipify.org

log() {
  echo "== $*"
}

in_device() {
  sudo ip netns exec "$NETNS" "$@"
}

isp_rules() {
  sudo iptables-nft -t nat "$1" POSTROUTING -s "$LAN_SUBNET" -o "$INTERNET_BRIDGE" -j MASQUERADE
  if [ "$1" = -A ]; then action=-I; else action="$1"; fi
  sudo iptables-nft "$action" DOCKER-USER -i "$LAN" -o "$INTERNET_BRIDGE" \
    -m comment --comment "$ISP_COMMENT" -j ACCEPT
  sudo iptables-nft "$action" DOCKER-USER -i "$INTERNET_BRIDGE" -o "$LAN" \
    -m conntrack --ctstate RELATED,ESTABLISHED -m comment --comment "$ISP_COMMENT" -j ACCEPT
}

cleanup() {
  if [ -n "${CLI:-}" ] && [ -f "$BOX/config.yaml" ]; then
    sudo "$CLI" down --dir "$BOX" >/dev/null 2>&1 || true
  fi
  if [ -n "${PY:-}" ] && [ -x "$PY" ]; then
    sudo "$PY" -c "from vibedpn.engine.router import remove_router; remove_router()" >/dev/null 2>&1 || true
  fi
  docker rm -f "$VPS" >/dev/null 2>&1 || true
  docker network rm "$INTERNET" >/dev/null 2>&1 || true
  sudo ip netns del "$NETNS" 2>/dev/null || true
  sudo ip link del "$LAN" 2>/dev/null || true
  isp_rules -D 2>/dev/null || true
  sudo rm -rf "$WORK"
}
trap cleanup EXIT

fail() {
  echo "FAIL: $*" >&2
  {
    echo "--- diagnostics"
    echo "# ip rule"; ip rule
    echo "# table 7760 (tor)"; ip route show table 7760 2>&1
    echo "# router table"; sudo nft list table inet vibedpn_router
    echo "# containers"; docker ps -a --format '{{.Names}} {{.Status}}'
    echo "# tor gateway"; docker logs --tail 20 vibedpn-tor-1
    echo "# tor gateway nft"; docker exec vibedpn-tor-1 nft list table ip vibedpn_tor
    echo "# core"; docker logs --tail 25 vibedpn-core-1
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
docker image inspect "$CORE_IMAGE" "$WG_IMAGE" "$TOR_IMAGE" >/dev/null 2>&1 ||
  fail "build $CORE_IMAGE, $WG_IMAGE and $TOR_IMAGE first (docker build -t ... core / images/wg / images/tor)"

HOST_ADDRESS="$(curl -s --max-time 15 "https://$ECHO_HOST" || true)"
[ -n "$HOST_ADDRESS" ] || fail "the host itself gets no answer from $ECHO_HOST: this stand needs the internet"
echo "host public address: $HOST_ADDRESS"

# --- the stand ----------------------------------------------------------------------------------
log "stand: the fake internet of the LAN's ISP, the LAN bridge and a device"
docker network create --subnet "$INTERNET_SUBNET" --gateway "$INTERNET_GATEWAY" \
  -o com.docker.network.bridge.name="$INTERNET_BRIDGE" \
  -o com.docker.network.bridge.gateway_mode_ipv4=nat-unprotected "$INTERNET" >/dev/null
sudo ip link add "$LAN" type bridge
sudo ip addr add "$BOX_LAN_IP/24" dev "$LAN"
sudo ip link set "$LAN" up
sudo ip netns add "$NETNS"
sudo ip link add e2e-dev type veth peer name e2e-lan
sudo ip link set e2e-lan master "$LAN" up
sudo ip link set e2e-dev netns "$NETNS"
in_device ip addr add "$DEVICE_IP/24" dev e2e-dev
in_device ip link set e2e-dev up
in_device ip link set lo up
in_device ip route add default via "$BOX_LAN_IP"
isp_rules -A
# The device has no path of its own to the real internet: its direct traffic ends in the fake one.
if in_device curl -s --max-time 5 "https://$ECHO_HOST" >/dev/null 2>&1; then
  fail "the device reaches $ECHO_HOST without the box: the stand could not tell Tor from direct"
fi

log "stand: the fake VPS the client role needs"
wg_tool() { docker run --rm -i --entrypoint wg "$WG_IMAGE" "$@"; }
server_key="$(wg_tool genkey)"
client_key="$(wg_tool genkey)"
server_pub="$(printf '%s' "$server_key" | wg_tool pubkey)"
client_pub="$(printf '%s' "$client_key" | wg_tool pubkey)"
mkdir -m 700 "$WORK/vps"
cat >"$WORK/vps/wg0.conf" <<EOF
[Interface]
Address = 10.78.0.1/24
ListenPort = 51820
PrivateKey = $server_key

[Peer]
PublicKey = $client_pub
AllowedIPs = 10.78.0.2/32
EOF
cat >"$WORK/peer.conf" <<EOF
[Interface]
PrivateKey = $client_key
Address = 10.78.0.2/32

[Peer]
PublicKey = $server_pub
Endpoint = $INTERNET_GATEWAY:$VPS_PORT
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
EOF
chmod 600 "$WORK/vps/wg0.conf" "$WORK/peer.conf"
docker run -d --name "$VPS" --network "$INTERNET" --ip "$VPS_IP" --cap-add NET_ADMIN \
  --sysctl net.ipv4.ip_forward=1 -p "$VPS_PORT:51820/udp" \
  -v "$WORK/vps:/etc/wireguard:ro" "$WG_IMAGE" server >/dev/null

# --- the box ------------------------------------------------------------------------------------
log "box: role client, LAN on $LAN, AdGuard on, ui off, uplink tor enabled"
mkdir "$BOX"
cp "$REPO/compose.yaml" "$BOX/"
printf '%s\n' "$PASSWORD" >"$WORK/password"
sudo "$CLI" init --dir "$BOX" --role client --peer-config "$WORK/peer.conf" \
  --password-file "$WORK/password" >/dev/null
sudo sed -i \
  -e "s/^  lan_interface: .*/  lan_interface: $LAN/" \
  -e "s#^  lan_subnet: .*#  lan_subnet: $LAN_SUBNET#" \
  -e "s/^  lan_address: .*/  lan_address: $BOX_LAN_IP/" \
  "$BOX/config.yaml"
sudo sed -i '/^ui:/,/^$/ s/enabled: true/enabled: false/' "$BOX/config.yaml"
sudo sed -i "s/^VIBEDPN_TAG=.*/VIBEDPN_TAG=$TAG/" "$BOX/.env"
sudo "$CLI" tor enable --dir "$BOX" | grep -q "enabled with 2 bridges" || fail "vibedpn tor enable failed"

wait_healthy() {
  i=0
  until [ "$(docker inspect -f '{{.State.Health.Status}}' "$1" 2>/dev/null || true)" = healthy ]; do
    i=$((i + 2))
    [ "$i" -lt "$2" ] || fail "$1 never became healthy"
    sleep 2
  done
}
# The address of ECHO_HOST as the box's DNS gives it to the device: asking it is also what fills the
# channel set of a domain rule.
device_resolve() {
  in_device "$PY" -c 'import socket, struct, sys
labels = b"".join(bytes([len(p)]) + p.encode() for p in sys.argv[1].split("."))
q = struct.pack("!HHHHHH", 11, 0x0100, 1, 0, 0, 0) + labels + b"\x00" + struct.pack("!HH", 1, 1)
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(8); s.sendto(q, (sys.argv[2], 53))
data = s.recvfrom(4096)[0]
count = struct.unpack("!H", data[6:8])[0]
at = 12
while data[at]:
    at += data[at] + 1
at += 5
for _ in range(count):
    at += 2 if data[at] & 0xC0 == 0xC0 else data.index(0, at) - at + 1
    kind, _cls, _ttl, size = struct.unpack("!HHIH", data[at:at + 10])
    at += 10
    if kind == 1:
        print(socket.inet_ntoa(data[at:at + 4]))
        break
    at += size' "$1" "$BOX_LAN_IP"
}
# What the echo service reports for the device, or nothing: the name is pinned to $1 so the device
# does not depend on a resolver for the request itself.
device_exit() {
  in_device curl -s --max-time 30 --resolve "$ECHO_HOST:443:$1" "https://$ECHO_HOST" 2>/dev/null || true
}
# $1: the echo address; $2: "tor" (an answer that is not the host's) or "none"; $3: what failed.
await_device_exit() {
  i=0
  while :; do
    seen="$(device_exit "$1")"
    if [ "$2" = none ]; then
      [ -z "$seen" ] && return 0
    elif [ -n "$seen" ] && [ "$seen" != "$HOST_ADDRESS" ]; then
      echo "device exit: $seen"
      return 0
    fi
    i=$((i + 5))
    [ "$i" -lt 240 ] || fail "$3 (the echo service reports '${seen:-no answer}')"
    sleep 5
  done
}

sudo "$CLI" up --dir "$BOX" >/dev/null 2>&1 || fail "vibedpn up failed"
wait_healthy vibedpn-core-1 "$TIMEOUT"
log "box: waiting for the tor gateway to bootstrap (Snowflake, up to $TOR_TIMEOUT s)"
wait_healthy vibedpn-tor-1 "$TOR_TIMEOUT"
[ -s "$BOX/data/tor/config/bridges" ] || fail "core did not write data/tor/config/bridges"
ECHO_ADDRESS="$(device_resolve "$ECHO_HOST")"
[ -n "$ECHO_ADDRESS" ] || fail "the box's DNS gave the device no address for $ECHO_HOST"
echo "$ECHO_HOST resolves to $ECHO_ADDRESS through the box"

# --- checks -------------------------------------------------------------------------------------
log "full through tor: the device leaves through Tor, not with the host's address"
sudo "$CLI" upstream tor --dir "$BOX" >/dev/null || fail "vibedpn upstream tor failed"
sudo "$CLI" mode full --dir "$BOX" >/dev/null || fail "vibedpn mode full failed"
await_device_exit "$ECHO_ADDRESS" tor "mode full through tor does not carry the device"
report="$(sudo "$CLI" doctor --network --dir "$BOX" || true)"
printf '%s\n' "$report" | grep -E "exit (direct|tor)" || true
printf '%s\n' "$report" | grep -q "\[ ok \] exit tor" || fail "doctor --network does not confirm the exit of tor"

log "kill switch: a stopped tor gateway leaves the device without a way out, never direct"
docker stop vibedpn-tor-1 >/dev/null
await_device_exit "$ECHO_ADDRESS" none "with the tor gateway stopped the device still gets out"
docker start vibedpn-tor-1 >/dev/null
wait_healthy vibedpn-tor-1 "$TOR_TIMEOUT"
await_device_exit "$ECHO_ADDRESS" tor "the device does not get back through tor after its gateway returned"

log "smart: a network rule sends the echo address through tor, its removal takes it back"
sudo "$CLI" mode smart --dir "$BOX" >/dev/null || fail "vibedpn mode smart failed"
await_device_exit "$ECHO_ADDRESS" none "in smart without rules the device still leaves through an uplink"
sudo "$CLI" net add "$ECHO_ADDRESS/32" tor --dir "$BOX" | grep -q "via tor, applied" || fail "vibedpn net add failed"
await_device_exit "$ECHO_ADDRESS" tor "a network rule via tor does not carry the device"
sudo "$CLI" net rm "$ECHO_ADDRESS/32" --dir "$BOX" | grep -q "rule removed" || fail "vibedpn net rm failed"
await_device_exit "$ECHO_ADDRESS" none "after net rm the device still leaves through tor"

log "smart: a domain rule via tor follows the name the device asks the box for"
sudo "$CLI" rule add ipify.org tor --dir "$BOX" | grep -q "via tor, applied" || fail "vibedpn rule add via tor failed"
i=0
until ECHO_ADDRESS="$(device_resolve "$ECHO_HOST")" && [ -n "$ECHO_ADDRESS" ] &&
  [ -n "$(device_exit "$ECHO_ADDRESS")" ]; do
  i=$((i + 5))
  [ "$i" -lt 240 ] || fail "a domain rule via tor does not carry $ECHO_HOST"
  sleep 5
done
await_device_exit "$ECHO_ADDRESS" tor "a domain rule via tor answers with the host's address"

log "E2E-TOR-OK"
