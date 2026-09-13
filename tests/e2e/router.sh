#!/bin/sh
# E2E stand of a client box: fake VPS + the box + a LAN device, on one Linux host with Docker.
#
# What runs is the product itself: `vibedpn init/up/mode/doctor`, core and wg-client images of the
# repository, AdGuard Home. Around it the stand builds, without the real internet:
#   - network e2e-internet (198.18.0.0/24, RFC 2544 benchmark range, bridge e2einet0) with a web
#     container at 198.18.0.10 that answers with the address it sees — the exit address;
#   - a fake VPS: vibedpn/wg in mode server at 198.18.0.20 with NAT, its port published on the host;
#   - the LAN: bridge lan0 (box 192.168.77.1) with a device in the netns e2e-lanhost;
#   - the ISP path of that LAN: NAT from the LAN into e2einet0, seen as 198.18.0.1.
# So "through the VPS" and "direct" are two different exit addresses, not a guess from counters.
# A one-port LAN (the ISP router on the wire of the host's own interface) is not reproduced here.
#
# Needs: Linux, Docker Engine >= 28, the wireguard module, sudo, curl, python3 (or a python with the
# CLI installed in VIBEDPN_E2E_PYTHON), images ghcr.io/borodatych/vibedpn-{core,wg}:$VIBEDPN_TAG.
# VIBEDPN_E2E_OFFLINE=1 skips the DNS checks, the only ones that need the internet (DoH upstream).
set -eu

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
TAG="${VIBEDPN_TAG:-e2e}"
WG_IMAGE="ghcr.io/borodatych/vibedpn-wg:$TAG"
CORE_IMAGE="ghcr.io/borodatych/vibedpn-core:$TAG"
OFFLINE="${VIBEDPN_E2E_OFFLINE:-0}"
WORK="$(mktemp -d)"
BOX="$WORK/box"
PASSWORD=e2e-pass-123

INTERNET=e2e-internet
INTERNET_BRIDGE=e2einet0
INTERNET_SUBNET=198.18.0.0/24
INTERNET_GATEWAY=198.18.0.1
WEB=e2e-web
WEB_IP=198.18.0.10
WEB_PORT=8080
VPS=e2e-vps
VPS_IP=198.18.0.20
VPS_PORT=51899
LAN=lan0
LAN_SUBNET=192.168.77.0/24
BOX_LAN_IP=192.168.77.1
DEVICE_IP=192.168.77.2
NETNS=e2e-lanhost
# A second device on the same LAN: policies of one must not touch the other.
DEVICE2_IP=192.168.77.3
NETNS2=e2e-lanhost2
LISTENER=e2e-listener
LISTENER_IP=10.77.0.99
LISTENER_PORT=4050
ISP_COMMENT=e2e-isp
TIMEOUT=60

log() {
  echo "== $*"
}

in_device() {
  sudo ip netns exec "$NETNS" "$@"
}

isp_rules() {
  # $1: -A/-I to add, -D to delete; the NAT and the transit Docker's forward drop would kill.
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
  # `down` stops core, and a stopped core leaves the router on the host on purpose (no leak while it
  # restarts). The stand is not a box: marks, rules, uplink tables and DOCKER-USER transit go too.
  if [ -n "${PY:-}" ] && [ -x "$PY" ]; then
    sudo "$PY" -c "from vibedpn.engine.router import remove_router; remove_router()" >/dev/null 2>&1 || true
  fi
  docker rm -f "$WEB" "$VPS" "$LISTENER" >/dev/null 2>&1 || true
  docker network rm "$INTERNET" >/dev/null 2>&1 || true
  sudo ip netns del "$NETNS" 2>/dev/null || true
  sudo ip netns del "$NETNS2" 2>/dev/null || true
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
    echo "# table 7710"; ip route show table 7710 2>&1
    echo "# DOCKER-USER"; sudo iptables-nft -S DOCKER-USER
    echo "# router table"; sudo nft list table inet vibedpn_router
    echo "# containers"; docker ps -a --format '{{.Names}} {{.Status}}'
    echo "# wg-client"; docker exec vibedpn-wg-client-1 wg show wg0
    echo "# fake VPS"; docker exec "$VPS" wg show wg0
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
docker image inspect "$CORE_IMAGE" "$WG_IMAGE" >/dev/null 2>&1 ||
  fail "build $CORE_IMAGE and $WG_IMAGE first (docker build -t ... core / images/wg)"

# --- the stand ----------------------------------------------------------------------------------
log "stand: the internet, a web server that answers with the exit address"
# nat-unprotected: in the default nat mode Docker drops, in raw PREROUTING, every packet addressed
# to a container IP that does not arrive on its own bridge (`-d <ip> ! -i <bridge> -j DROP`) — the
# device's packet to the web server would die on lan0 before the router ever marked it. The real
# internet has no such guard, so the stand's internet must not have it either.
docker network create --subnet "$INTERNET_SUBNET" --gateway "$INTERNET_GATEWAY" \
  -o com.docker.network.bridge.name="$INTERNET_BRIDGE" \
  -o com.docker.network.bridge.gateway_mode_ipv4=nat-unprotected "$INTERNET" >/dev/null
docker run -d --name "$WEB" --network "$INTERNET" --ip "$WEB_IP" --entrypoint python "$CORE_IMAGE" -c "
import http.server
class Echo(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = self.client_address[0].encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args):
        pass
http.server.ThreadingHTTPServer(('0.0.0.0', $WEB_PORT), Echo).serve_forever()
" >/dev/null

log "stand: the LAN bridge, a device, and the ISP path of that LAN"
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
sudo ip netns add "$NETNS2"
sudo ip link add e2e-dev2 type veth peer name e2e-lan2
sudo ip link set e2e-lan2 master "$LAN" up
sudo ip link set e2e-dev2 netns "$NETNS2"
sudo ip netns exec "$NETNS2" ip addr add "$DEVICE2_IP/24" dev e2e-dev2
sudo ip netns exec "$NETNS2" ip link set e2e-dev2 up
sudo ip netns exec "$NETNS2" ip link set lo up
sudo ip netns exec "$NETNS2" ip route add default via "$BOX_LAN_IP"
isp_rules -A

log "stand: the fake VPS end of the tunnel, with its own way out"
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
# The endpoint is the host address on the internet bridge: the published port answers there.
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
i=0
until docker exec "$VPS" /usr/local/bin/entrypoint.sh health >/dev/null 2>&1; do
  i=$((i + 1))
  [ "$i" -lt "$TIMEOUT" ] || fail "the fake VPS did not come up"
  sleep 1
done
printf 'table ip e2e {\n  chain postrouting {\n    type nat hook postrouting priority srcnat;\n    oifname "eth0" masquerade\n  }\n}\n' |
  docker exec -i "$VPS" nft -f -

# --- the box ------------------------------------------------------------------------------------
log "box: role client, LAN on $LAN, AdGuard on, ui off, routing full"
mkdir "$BOX"
cp "$REPO/compose.yaml" "$BOX/"
printf '%s\n' "$PASSWORD" >"$WORK/password"
sudo "$CLI" init --dir "$BOX" --role client --peer-config "$WORK/peer.conf" \
  --password-file "$WORK/password" >/dev/null
sudo sed -i \
  -e "s/^  lan_interface: .*/  lan_interface: $LAN/" \
  -e "s#^  lan_subnet: .*#  lan_subnet: $LAN_SUBNET#" \
  -e "s/^  lan_address: .*/  lan_address: $BOX_LAN_IP/" \
  -e "s/^  mode: off$/  mode: full/" \
  "$BOX/config.yaml"
sudo sed -i '/^ui:/,/^$/ s/enabled: true/enabled: false/' "$BOX/config.yaml"
sudo sed -i "s/^VIBEDPN_TAG=.*/VIBEDPN_TAG=$TAG/" "$BOX/.env"

wait_healthy() {
  i=0
  until [ "$(docker inspect -f '{{.State.Health.Status}}' "$1" 2>/dev/null || true)" = healthy ]; do
    i=$((i + 1))
    [ "$i" -lt "$TIMEOUT" ] || fail "$1 never became healthy"
    sleep 2
  done
}
# The address the web server sees for the device in netns $1, or nothing when it gets no answer.
exit_address_in() {
  sudo ip netns exec "$1" curl -s --max-time 4 "http://$WEB_IP:$WEB_PORT/" 2>/dev/null || true
}
exit_address() {
  exit_address_in "$NETNS"
}
# $1: the device netns; $2: the wanted exit address, or "none"; $3: what failed.
await_exit_in() {
  i=0
  while :; do
    seen="$(exit_address_in "$1")"
    [ "$2" = none ] && [ -z "$seen" ] && return 0
    [ "$seen" = "$2" ] && return 0
    i=$((i + 1))
    [ "$i" -lt "$TIMEOUT" ] || fail "$3 (the web server sees '${seen:-no connection}')"
    sleep 1
  done
}
await_exit() {
  await_exit_in "$NETNS" "$1" "$2"
}
# The ICMP probe core itself uses (the host may have no ping), and a plain TCP connect.
PROBE='import sys; from vibedpn.engine.probe import ping; sys.exit(0 if ping(sys.argv[1], 2.0) else 1)'
CONNECT='import socket, sys; socket.create_connection((sys.argv[1], int(sys.argv[2])), 3).close()'
# DNS answers for google.com from AdGuard on the box, asked from the device.
dns_answers() {
  in_device "$PY" -c 'import socket, struct, sys
q = struct.pack("!HHHHHH", 9, 0x0100, 1, 0, 0, 0) + b"\x06google\x03com\x00" + struct.pack("!HH", int(sys.argv[1]), 1)
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(5); s.sendto(q, (sys.argv[2], 53))
print(struct.unpack("!H", s.recvfrom(2048)[0][6:8])[0])' "$1" "$BOX_LAN_IP"
}
await_dns() {
  i=0
  until dns_answers 1 >/dev/null 2>&1; do
    i=$((i + 1))
    [ "$i" -lt "$TIMEOUT" ] || fail "AdGuard does not answer on $BOX_LAN_IP:53"
    sleep 1
  done
}
wg_started() {
  docker inspect -f '{{.State.StartedAt}}' vibedpn-wg-client-1
}

sudo "$CLI" up --dir "$BOX" >/dev/null 2>&1 || fail "vibedpn up failed"
wait_healthy vibedpn-core-1
wait_healthy vibedpn-wg-client-1

# --- checks -------------------------------------------------------------------------------------
log "full: the device leaves through the VPS ($VPS_IP)"
await_exit "$VPS_IP" "the device does not leave through the VPS in mode full"
echo "exit address: $(exit_address)"
sudo "$CLI" doctor --dir "$BOX" | grep "router" || true
sudo "$CLI" doctor --dir "$BOX" | grep -q "\[ ok \] router" || fail "doctor does not confirm the router"
# doctor --network against the stand's echo server: the host goes direct, wg-client through the VPS.
network_report="$(sudo env VIBEDPN_EXIT_IP_URL="http://$WEB_IP:$WEB_PORT/" "$CLI" doctor --network --dir "$BOX" || true)"
printf '%s\n' "$network_report" | grep -E "exit |dns leak" || true
printf '%s\n' "$network_report" | grep -q "\[ ok \] exit direct *$INTERNET_GATEWAY" ||
  fail "doctor --network: wrong direct exit"
printf '%s\n' "$network_report" | grep -q "\[ ok \] exit vps *$VPS_IP" ||
  fail "doctor --network: uplink vps does not exit through the VPS"
printf '%s\n' "$network_report" | grep -q "\[warn\] dns leak" ||
  fail "doctor --network: no DoH warning in mode full"

log "devices: the LAN device is discovered, and kept across a core restart"
device_mac="$(in_device cat /sys/class/net/e2e-dev/address)"
first_seen() {
  sudo "$PY" -c 'import sqlite3, sys
row = sqlite3.connect(sys.argv[1]).execute("SELECT first_seen FROM devices WHERE mac = ?", (sys.argv[2],)).fetchone()
print(row[0] if row else "")' "$BOX/data/core/devices.db" "$device_mac"
}
i=0
until "$CLI" device list --dir "$BOX" 2>/dev/null | grep -q "$device_mac"; do
  i=$((i + 1))
  [ "$i" -lt "$TIMEOUT" ] || fail "the device $device_mac never appeared in vibedpn device list"
  sleep 2
done
"$CLI" device list --dir "$BOX"
seen_before="$(first_seen)"
[ -n "$seen_before" ] || fail "the device is listed but not stored in devices.db"
docker restart vibedpn-core-1 >/dev/null
wait_healthy vibedpn-core-1
"$CLI" device list --dir "$BOX" | grep -q "$device_mac" || fail "the device is gone after a core restart"
[ "$(first_seen)" = "$seen_before" ] || fail "a core restart reset first_seen of the device"
echo "device $device_mac listed and kept across a core restart"

log "device policies at runtime: vibedpn device set/unset, no core restart"
core_started="$(docker inspect -f '{{.State.StartedAt}}' vibedpn-core-1)"
"$CLI" device set "$device_mac" bypass --name e2e-device --dir "$BOX" || fail "vibedpn device set bypass failed"
await_exit "$INTERNET_GATEWAY" "policy bypass did not send the device direct in mode full"
echo "bypass: exit address $(exit_address)"
grep -q "policy: bypass" "$BOX/config.yaml" || fail "vibedpn device set did not write config.yaml"
"$CLI" device set "$device_mac" block --dir "$BOX" || fail "vibedpn device set block failed"
await_exit none "policy block still lets the device out"
echo "block: no exit"
"$CLI" device unset "$device_mac" --dir "$BOX" || fail "vibedpn device unset failed"
await_exit "$VPS_IP" "after unset the device does not follow routing.mode full again"
echo "unset: exit address $(exit_address)"
[ "$(docker inspect -f '{{.State.StartedAt}}' vibedpn-core-1)" = "$core_started" ] ||
  fail "a device policy change restarted core"

log "two devices, different policies at the same time"
device2_mac="$(sudo ip netns exec "$NETNS2" cat /sys/class/net/e2e-dev2/address)"
# 1. full; the second device bypasses: one through the VPS, the other direct.
"$CLI" device set "$device2_mac" bypass --name e2e-device-2 --dir "$BOX" >/dev/null ||
  fail "vibedpn device set bypass for the second device failed"
await_exit_in "$NETNS2" "$INTERNET_GATEWAY" "the second device (bypass) does not go direct"
await_exit "$VPS_IP" "the first device left the VPS when the second one got bypass"
echo "full, second bypass: first $(exit_address), second $(exit_address_in "$NETNS2")"
# 2. the second device is blocked; the first one keeps its way out.
"$CLI" device set "$device2_mac" block --dir "$BOX" >/dev/null || fail "vibedpn device set block failed"
await_exit_in "$NETNS2" none "the blocked second device still gets out"
await_exit "$VPS_IP" "the first device lost the VPS when the second one was blocked"
echo "full, second block: first $(exit_address), second no exit"
# 3. mode off; the first device keeps the VPS by its own policy, the second one goes direct.
"$CLI" device unset "$device2_mac" --dir "$BOX" >/dev/null || fail "vibedpn device unset failed"
"$CLI" device set "$device_mac" vps --dir "$BOX" >/dev/null || fail "vibedpn device set vps failed"
core_started="$(docker inspect -f '{{.State.StartedAt}}' vibedpn-core-1)"
"$CLI" mode off --dir "$BOX" | grep -q "applied live" || fail "vibedpn mode off did not apply live through core"
await_exit "$VPS_IP" "policy vps does not keep the first device on the VPS in mode off"
await_exit_in "$NETNS2" "$INTERNET_GATEWAY" "the second device does not go direct in mode off"
echo "off, first vps: first $(exit_address), second $(exit_address_in "$NETNS2")"
# 4. the gateway stops (failopen false): the first device is held, the second one stays direct.
docker stop vibedpn-wg-client-1 >/dev/null
await_exit none "the first device (policy vps) still gets out with the gateway stopped"
await_exit_in "$NETNS2" "$INTERNET_GATEWAY" "the kill switch of vps took the direct device down too"
echo "gateway stopped: first held, second $(exit_address_in "$NETNS2")"
docker start vibedpn-wg-client-1 >/dev/null
wait_healthy vibedpn-wg-client-1
await_exit "$VPS_IP" "the first device did not come back through the VPS with the gateway"
"$CLI" device list --dir "$BOX" | grep -q "$device2_mac" ||
  fail "the second device $device2_mac is not in vibedpn device list"
# 5. back to the start: no own policies, mode full.
"$CLI" device unset "$device_mac" --dir "$BOX" >/dev/null || fail "vibedpn device unset failed"
"$CLI" mode full --dir "$BOX" | grep -q "applied live" || fail "vibedpn mode full did not apply live through core"
await_exit "$VPS_IP" "the first device does not return to the VPS in mode full"
await_exit_in "$NETNS2" "$VPS_IP" "the second device does not follow mode full back to the VPS"
echo "full again: both devices through the VPS"
[ "$(docker inspect -f '{{.State.StartedAt}}' vibedpn-core-1)" = "$core_started" ] ||
  fail "a routing mode change restarted core"
"$CLI" status --dir "$BOX" | grep -q "uplink vps: gateway answers" || fail "vibedpn status does not show the vps gateway"

log "the LAN never reaches a gateway container directly"
in_device "$PY" -c "$PROBE" "$BOX_LAN_IP" ||
  fail "the ICMP probe does not work from the device netns, so the next check would prove nothing"
sudo "$PY" -c "$PROBE" 10.77.0.10 ||
  fail "10.77.0.10 does not answer the box itself, so its silence to the device proves nothing"
if in_device "$PY" -c "$PROBE" 10.77.0.10; then
  fail "the device reached 10.77.0.10 directly"
fi
docker run -d --name "$LISTENER" --network vibedpn-upstreams --ip "$LISTENER_IP" \
  --entrypoint sh "$WG_IMAGE" -c "while true; do echo ok | nc -l -p $LISTENER_PORT; done" >/dev/null
i=0
until "$PY" -c "$CONNECT" "$LISTENER_IP" "$LISTENER_PORT" 2>/dev/null; do
  i=$((i + 1))
  [ "$i" -lt 10 ] || fail "the listener on the gateway network does not answer the box, so the next check would prove nothing"
  sleep 1
done
if in_device "$PY" -c "$CONNECT" "$LISTENER_IP" "$LISTENER_PORT" 2>/dev/null; then
  fail "the device opened TCP to $LISTENER_IP:$LISTENER_PORT on the gateway network"
fi
docker rm -f "$LISTENER" >/dev/null
echo "10.77.0.10 (icmp) and $LISTENER_IP:$LISTENER_PORT (tcp): open to the box, closed to the device"

if [ "$OFFLINE" = 1 ]; then
  echo "DNS checks skipped (VIBEDPN_E2E_OFFLINE=1): AdGuard needs its DoH upstream"
else
  log "DNS: AdGuard on the box, empty AAAA in full, the init password"
  await_dns
  [ "$(dns_answers 1)" -gt 0 ] || fail "AdGuard gives the device no A answer"
  [ "$(dns_answers 28)" = 0 ] || fail "AdGuard answers AAAA in mode full"
  login="$(curl -s -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' \
    -d "{\"name\":\"admin\",\"password\":\"$PASSWORD\"}" "http://$BOX_LAN_IP:3000/control/login")"
  [ "$login" = 200 ] || fail "AdGuard does not accept the password from vibedpn init ($login)"
  echo "A answered, AAAA empty, AdGuard login 200"
fi

log "kill switch (failopen false): the gateway stops, the device is cut off, and comes back"
docker stop vibedpn-wg-client-1 >/dev/null
await_exit none "the device still reaches the internet with the gateway stopped"
echo "gateway stopped: no exit"
docker start vibedpn-wg-client-1 >/dev/null
wait_healthy vibedpn-wg-client-1
await_exit "$VPS_IP" "the device did not come back through the VPS with the gateway"

log "failopen true: the gateway stops and the device goes direct ($INTERNET_GATEWAY)"
sudo sed -i 's/^  failopen: false$/  failopen: true/' "$BOX/config.yaml"
sudo "$CLI" restart --dir "$BOX" >/dev/null 2>&1 || fail "vibedpn restart failed"
wait_healthy vibedpn-core-1
wait_healthy vibedpn-wg-client-1
await_exit "$VPS_IP" "the device does not leave through the VPS after switching to failopen true"
docker stop vibedpn-wg-client-1 >/dev/null
await_exit "$INTERNET_GATEWAY" "failopen true did not let the device out directly"
echo "gateway stopped: exit address $(exit_address)"
docker start vibedpn-wg-client-1 >/dev/null
wait_healthy vibedpn-wg-client-1
await_exit "$VPS_IP" "the device did not return to the VPS with the gateway"

log "vibedpn mode off: direct, only core (and adguard) restart"
started="$(wg_started)"
sudo "$CLI" mode off --dir "$BOX" | tee "$WORK/mode.txt"
grep -q "core, adguard restarted" "$WORK/mode.txt" || fail "vibedpn mode off did not restart core and adguard"
wait_healthy vibedpn-core-1
await_exit "$INTERNET_GATEWAY" "the device does not go direct in mode off"
[ "$(wg_started)" = "$started" ] || fail "vibedpn mode off restarted wg-client"
"$CLI" status --dir "$BOX" | grep -q "^routing: mode=off" || fail "status does not show mode off"
if [ "$OFFLINE" != 1 ]; then
  await_dns
  [ "$(dns_answers 28)" -gt 0 ] || fail "AdGuard still hides AAAA in mode off"
  echo "AAAA answered in mode off"
fi

log "vibedpn mode full: through the VPS again"
sudo "$CLI" mode full --dir "$BOX" >/dev/null
wait_healthy vibedpn-core-1
await_exit "$VPS_IP" "the device does not return to the VPS after vibedpn mode full"
[ "$(wg_started)" = "$started" ] || fail "vibedpn mode full restarted wg-client"
if [ "$OFFLINE" != 1 ]; then
  await_dns
  [ "$(dns_answers 28)" = 0 ] || fail "AdGuard answers AAAA again in mode full"
fi
sudo "$CLI" mode full --dir "$BOX" | grep -q "already set" || fail "a repeated mode was not recognised"

log "E2E-ROUTER-OK"
