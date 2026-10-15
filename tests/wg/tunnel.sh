#!/bin/sh
# A real tunnel between two vibedpn/wg containers: handshake, traffic through the tunnel, and the
# client kill switch (nothing leaves except the tunnel, even when it breaks).
#
# The whole scenario runs once per flavor of the config files:
#   plain  a WireGuard file as a provider hands it out: no obfuscation keys at all
#   awg2   AmneziaWG 2.0 keys: junk packets, paddings S1-S4, header ranges H1-H4, a signature packet
#   awg3   AmneziaWG 3.1 keys: header protection, content padding, random trailers, cookies off
# A tunnel whose obfuscation keys differ from the server's must never handshake (checked in the
# awg flavors), which is the proof that the keys act on the wire and are not just accepted.
#
# Needs a Linux host with /dev/net/tun and a Docker daemon (the daemon makes the interface from the
# TUN device, no kernel module is involved). The image is taken from VIBEDPN_WG_IMAGE (default: the
# tag the repository builds). VIBEDPN_WG_FLAVOR runs one flavor instead of all.
set -eu

FLAVORS="plain awg2 awg3"
if [ -z "${VIBEDPN_WG_FLAVOR:-}" ]; then
  for flavor in $FLAVORS; do
    echo "######## flavor $flavor"
    VIBEDPN_WG_FLAVOR="$flavor" sh "$0"
  done
  exit 0
fi
FLAVOR="$VIBEDPN_WG_FLAVOR"

IMAGE="${VIBEDPN_WG_IMAGE:-ghcr.io/borodatych/vibedpn-wg:test}"
NETWORK=vibedpn-wg-test
SUBNET=10.99.0.0/24
GATEWAY=10.99.0.1
SERVER_IP=10.99.0.2
CLIENT_IP=10.99.0.3
SPLIT_IP=10.99.0.4
ROUTER_IP=10.99.0.5
LAN_NETWORK=vibedpn-wg-lan-test
LAN_SUBNET=10.98.0.0/24
ROUTER_LAN_IP=10.98.0.254
LAN_HOST_IP=10.98.0.2
PROBE_PORT=8443
# The client file sets MTU 1400: an IPv4 SYN through it may carry at most 1400 - 40.
CLAMPED_MSS=1360
SERVER_WG=10.78.0.1
CLIENT_WG=10.78.0.2
SPLIT_WG=10.78.0.3
EXTRA_WG=10.78.0.9
LISTEN_PORT=51820
TUN_DEVICE=/dev/net/tun
# The control socket of the daemon; compose.yaml shares this directory of wg-server with core.
SOCKET_DIR=/var/run/amneziawg
# Peer whose obfuscation keys differ from the server's: it must never handshake (awg flavors).
MISMATCH_IP=10.99.0.6
MISMATCH_WG=10.78.0.5
MISMATCH_SECONDS=20
# Vanilla WireGuard (wireguard-go of Alpine, not our daemon): the plain flavor has to speak to it.
VANILLA_IP=10.99.0.7
VANILLA_WG=10.78.0.7
VANILLA_CLIENT_IP=10.99.0.8
VANILLA_CLIENT_WG=10.78.0.8
VANILLA_IMAGE=alpine:3.24
VANILLA_TIMEOUT=90
# What the entrypoint takes off the 1420 of a tunnel that gives no MTU: S4 bytes of padding in
# front of every transport packet. 0 for a plain file.
DEFAULT_MTU=1420
# TMPDIR must be a directory the Docker daemon sees (on macOS with a VM: under the shared home)
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/vibedpn-wg.XXXXXX")"
HANDSHAKE_TIMEOUT=30
OUTSIDE=8.8.8.8  # never reached: either the kill switch drops it or the tunnel has no exit

log() {
  echo "== $*"
}

cleanup() {
  docker rm -f vibedpn-wg-server vibedpn-wg-client vibedpn-wg-split vibedpn-wg-host vibedpn-wg-empty vibedpn-wg-lan \
    vibedpn-wg-router vibedpn-wg-mismatch vibedpn-wg-vanilla vibedpn-wg-vanilla-client >/dev/null 2>&1 || true
  # The host-namespace part of the test may leave wg0 behind; remove it without needing root.
  docker run --rm --network host --cap-add NET_ADMIN --entrypoint ip "$IMAGE" \
    link del wg0 >/dev/null 2>&1 || true
  docker network rm "$NETWORK" "$LAN_NETWORK" >/dev/null 2>&1 || true
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

awg_tool() {
  # -i: `awg pubkey` reads the key on stdin.
  docker run --rm -i --entrypoint awg "$IMAGE" "$@"
}

in_client() {
  docker exec vibedpn-wg-client "$@"
}

fails() {
  # The command must fail *inside a running container*: a `docker exec` that errors because the
  # container is gone would otherwise pass a leak check for the wrong reason.
  running="$(docker inspect -f '{{.State.Running}}' vibedpn-wg-client)"
  if [ "$running" != true ]; then
    echo "FAIL: the client container is not running, so '$*' proves nothing" >&2
    exit 1
  fi
  if "$@" >/dev/null 2>&1; then
    echo "FAIL: '$*' succeeded, but the kill switch had to drop it" >&2
    exit 1
  fi
}

log "keys (flavor $FLAVOR)"
server_key="$(awg_tool genkey)"
client_key="$(awg_tool genkey)"
split_key="$(awg_tool genkey)"
mismatch_key="$(awg_tool genkey)"
server_pub="$(printf '%s' "$server_key" | awg_tool pubkey)"
client_pub="$(printf '%s' "$client_key" | awg_tool pubkey)"
split_pub="$(printf '%s' "$split_key" | awg_tool pubkey)"
mismatch_pub="$(printf '%s' "$mismatch_key" | awg_tool pubkey)"
header_key="$(awg_tool genkey)"

# The obfuscation keys of the [Interface] section, the same on both ends. Values are not the ones a
# box generates: they only have to be far from the defaults, valid for awg and distinct per type
# (the size of a handshake message is 148 + S1, 92 + S2, 64 + S3, and S1 + 148 must not equal S2 + 92).
awg_interface_keys() {
  case "$FLAVOR" in
    plain) ;;
    awg2)
      cat <<KEYS
Jc = 4
Jmin = 40
Jmax = 70
S1 = 31
S2 = 45
S3 = 17
S4 = 23
H1 = 100000-200000
H2 = 300000-400000
H3 = 500000-600000
H4 = 700000-800000
I1 = <b 0xc0000000><r 16><t>
KEYS
      ;;
    awg3)
      cat <<KEYS
Jc = 4
Jmin = 40
Jmax = 70
S1 = 32
S2 = 32
S3 = 32
S4 = 32
H1 = 1
H2 = 2
H3 = 3
H4 = 4
HeaderProtectionKey = $header_key
ContentPaddingAddition = 8-24
RandomTrailers = on
DisableCookies = on
KEYS
      ;;
    *)
      echo "unknown flavor $FLAVOR" >&2
      exit 64
      ;;
  esac
}
case "$FLAVOR" in
  plain) S4_PADDING=0 ;;
  awg2) S4_PADDING=23 ;;
  awg3) S4_PADDING=32 ;;
esac

cat >"$WORK_DIR/server.conf" <<EOF
[Interface]
Address = $SERVER_WG/24
ListenPort = $LISTEN_PORT
PrivateKey = $server_key
$(awg_interface_keys)

[Peer]
PublicKey = $client_pub
AllowedIPs = $CLIENT_WG/32

[Peer]
PublicKey = $split_pub
AllowedIPs = $SPLIT_WG/32

[Peer]
PublicKey = $mismatch_pub
AllowedIPs = $MISMATCH_WG/32
EOF

# A home box that only wants to reach the VPS, not to exit through it: no 0.0.0.0/0, and no
# PersistentKeepalive either — the entrypoint has to mark its packets and add the keepalive
# itself, or the kill switch would strangle the handshake.
cat >"$WORK_DIR/split.conf" <<EOF
[Interface]
Address = $SPLIT_WG/32
PrivateKey = $split_key
$(awg_interface_keys)

[Peer]
PublicKey = $server_pub
Endpoint = $SERVER_IP:$LISTEN_PORT
AllowedIPs = 10.78.0.0/24
EOF

# Tabs, an "=" without spaces and a comment: the entrypoint has to read a config the way
# WireGuard does, not the way a single example happens to be formatted.
cat >"$WORK_DIR/client.conf" <<EOF
[Interface]
Address = fd00::2/128
	Address=$CLIENT_WG/32
PrivateKey = $client_key
MTU = 1400
DNS = 10.78.0.1   # a wg-quick key that awg setconf must never see
$(awg_interface_keys)

[Peer]
PublicKey = $server_pub
Endpoint = $SERVER_IP:$LISTEN_PORT
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
EOF
# A file written on Windows: every line ends with CRLF, and the entrypoint must still read it.
sed -e 's/$/\r/' "$WORK_DIR/client.conf" >"$WORK_DIR/client.crlf" &&
  mv "$WORK_DIR/client.crlf" "$WORK_DIR/client.conf"
chmod 600 "$WORK_DIR"/*.conf

log "network and containers"
docker network create --subnet "$SUBNET" --gateway "$GATEWAY" "$NETWORK" >/dev/null
# `--restart unless-stopped` is what compose.yaml gives both services; the self-healing check
# below depends on it. The server mounts a directory, like compose.yaml, so a config replaced by
# rename — the way core writes it — is visible inside.
SRV_DIR="$WORK_DIR/srv"
mkdir -m 700 "$SRV_DIR"
cp "$WORK_DIR/server.conf" "$SRV_DIR/wg0.conf"
chmod 600 "$SRV_DIR/wg0.conf"
docker run -d --name vibedpn-wg-server --network "$NETWORK" --ip "$SERVER_IP" \
  --restart unless-stopped --cap-add NET_ADMIN --device "$TUN_DEVICE" --sysctl net.ipv4.ip_forward=1 \
  -v "$SRV_DIR:/etc/wireguard:ro" "$IMAGE" server >/dev/null
docker run -d --name vibedpn-wg-client --network "$NETWORK" --ip "$CLIENT_IP" \
  --restart unless-stopped --cap-add NET_ADMIN --device "$TUN_DEVICE" --sysctl net.ipv4.ip_forward=1 \
  --sysctl net.ipv4.conf.all.src_valid_mark=1 \
  -v "$WORK_DIR/client.conf:/etc/wireguard/wg0.conf:ro" "$IMAGE" client >/dev/null
docker run -d --name vibedpn-wg-split --network "$NETWORK" --ip "$SPLIT_IP" \
  --restart unless-stopped --cap-add NET_ADMIN --device "$TUN_DEVICE" --sysctl net.ipv4.ip_forward=1 \
  --sysctl net.ipv4.conf.all.src_valid_mark=1 \
  -v "$WORK_DIR/split.conf:/etc/wireguard/wg0.conf:ro" "$IMAGE" client >/dev/null

await_health() {
  elapsed=0
  while [ "$elapsed" -lt "$HANDSHAKE_TIMEOUT" ]; do
    if docker exec "$1" /usr/local/bin/entrypoint.sh health >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  echo "FAIL: $1 was not healthy within ${HANDSHAKE_TIMEOUT}s" >&2
  docker logs --tail 20 "$1" >&2
  exit 1
}

# $1 present|absent, $2 a public key: wait until the running server agrees.
await_server_peer() {
  elapsed=0
  while [ "$elapsed" -lt "$HANDSHAKE_TIMEOUT" ]; do
    if docker exec vibedpn-wg-server awg show wg0 peers | grep -qxF "$2"; then
      found=present
    else
      found=absent
    fi
    [ "$found" = "$1" ] && return 0
    sleep 2
    elapsed=$((elapsed + 2))
  done
  echo "FAIL: peer $2 is not $1 on the server after ${HANDSHAKE_TIMEOUT}s" >&2
  docker logs --tail 10 vibedpn-wg-server >&2
  exit 1
}

same_restarts() {
  if [ "$(docker inspect -f '{{.RestartCount}}' "$1")" != "$2" ]; then
    echo "FAIL: $1 restarted, but a peer change has to be applied in place" >&2
    docker logs --tail 10 "$1" >&2
    exit 1
  fi
}

replace_server_conf() {
  cp "$1" "$SRV_DIR/.wg0.conf.new"
  chmod 600 "$SRV_DIR/.wg0.conf.new"
  mv "$SRV_DIR/.wg0.conf.new" "$SRV_DIR/wg0.conf"
}

log "handshake"
await_health vibedpn-wg-client
in_client /usr/local/bin/entrypoint.sh health
docker exec vibedpn-wg-server /usr/local/bin/entrypoint.sh health
docker exec vibedpn-wg-server awg show wg0 latest-handshakes

log "a split tunnel handshakes too: the kill switch must not strangle its own packets"
await_health vibedpn-wg-split
docker exec vibedpn-wg-split ping -c 2 -W 2 "$SERVER_WG"
docker exec vibedpn-wg-split awg show wg0 persistent-keepalive | grep -q 25
if docker exec vibedpn-wg-split ip route show table "$LISTEN_PORT" | grep -q default; then
  echo "FAIL: a split tunnel must not take over the default route" >&2
  exit 1
fi

log "traffic through the tunnel"
in_client ping -c 2 -W 2 "$SERVER_WG"
docker exec vibedpn-wg-server ping -c 2 -W 2 "$CLIENT_WG"

log "a tunnel that gives no MTU gets $DEFAULT_MTU less the S4 padding of its transport packets"
want_mtu=$((DEFAULT_MTU - S4_PADDING))
docker exec vibedpn-wg-split ip -o link show wg0 | grep -q "mtu $want_mtu " ||
  { echo "FAIL: the split tunnel has no MTU $want_mtu" >&2; exit 1; }
docker exec vibedpn-wg-server ip -o link show wg0 | grep -q "mtu $want_mtu " ||
  { echo "FAIL: the server has no MTU $want_mtu" >&2; exit 1; }

if [ "$FLAVOR" != plain ]; then
  log "the obfuscation keys are in effect: the server reports them, a peer without them never handshakes"
  docker exec vibedpn-wg-server awg show wg0 jc | grep -qx 4
  docker exec vibedpn-wg-server awg show wg0 s4 | grep -qx "$S4_PADDING"
  cat >"$WORK_DIR/mismatch.conf" <<EOF
[Interface]
Address = $MISMATCH_WG/24
PrivateKey = $mismatch_key

[Peer]
PublicKey = $server_pub
Endpoint = $SERVER_IP:$LISTEN_PORT
AllowedIPs = 10.78.0.0/24
PersistentKeepalive = 5
EOF
  chmod 600 "$WORK_DIR/mismatch.conf"
  # mode server: no kill switch and no watchdog, so the container lives on without a handshake
  docker run -d --name vibedpn-wg-mismatch --network "$NETWORK" --ip "$MISMATCH_IP" --cap-add NET_ADMIN \
    --device "$TUN_DEVICE" -v "$WORK_DIR/mismatch.conf:/etc/wireguard/wg0.conf:ro" "$IMAGE" server >/dev/null
  elapsed=0
  until docker exec vibedpn-wg-mismatch awg show wg0 peers | grep -qxF "$server_pub"; do
    elapsed=$((elapsed + 1))
    [ "$elapsed" -le "$HANDSHAKE_TIMEOUT" ] || { echo "FAIL: the mismatched peer did not start" >&2; exit 1; }
    sleep 1
  done
  sleep "$MISMATCH_SECONDS"
  if [ "$(docker inspect -f '{{.State.Running}}' vibedpn-wg-mismatch)" != true ]; then
    echo "FAIL: the mismatched peer is not running, so its silence proves nothing" >&2
    exit 1
  fi
  docker exec vibedpn-wg-mismatch awg show wg0 latest-handshakes | grep -q "^$server_pub.0$" ||
    { echo "FAIL: a peer without the obfuscation keys completed a handshake" >&2; exit 1; }
  docker exec vibedpn-wg-server awg show wg0 latest-handshakes | grep -q "^$mismatch_pub.0$" ||
    { echo "FAIL: the server answered a peer without the obfuscation keys" >&2; exit 1; }
  docker rm -f vibedpn-wg-mismatch >/dev/null
fi

log "the client applied the config: MTU from the file, default route in the tunnel"
in_client ip -o link show wg0 | grep -q "mtu 1400"
in_client ip route show table "$LISTEN_PORT" | grep -q "default dev wg0"
in_client ip rule show | grep -q "not.*fwmark 0xca6c lookup 51820"

log "kill switch: nothing leaves past the tunnel"
# The bridge gateway is one hop away through eth0 and the outside is a default route away:
# both are exactly the paths a leak would take, and both must be dropped.
fails in_client ping -c 1 -W 2 "$GATEWAY"
fails in_client ping -c 1 -W 2 "$OUTSIDE"
in_client nft list chain inet vibedpn_wg output | grep -q "policy drop"
in_client nft list chain inet vibedpn_wg forward | grep -q "policy drop"

log "the client is a gateway: a LAN host behind a router reaches the tunnel through it"
# The shape of a real box: the LAN is not on the gateway's own network. A LAN host sits on its
# own network behind a router (the box), the router hands its traffic to the client, and the
# client's main default route points back at the router — as it points at 10.77.0.1 on a box.
# Replies to the LAN host must leave the client that way, not fall into the full tunnel.
docker network create --subnet "$LAN_SUBNET" "$LAN_NETWORK" >/dev/null
docker run -d --name vibedpn-wg-router --network "$NETWORK" --ip "$ROUTER_IP" --cap-add NET_ADMIN \
  --sysctl net.ipv4.ip_forward=1 --entrypoint sleep "$IMAGE" 600 >/dev/null
docker network connect --ip "$ROUTER_LAN_IP" "$LAN_NETWORK" vibedpn-wg-router
docker run -d --name vibedpn-wg-lan --network "$LAN_NETWORK" --ip "$LAN_HOST_IP" --cap-add NET_ADMIN \
  --entrypoint sleep "$IMAGE" 600 >/dev/null
in_lan() {
  docker exec vibedpn-wg-lan "$@"
}
in_router() {
  docker exec vibedpn-wg-router "$@"
}
in_lan ip route replace default via "$ROUTER_LAN_IP"
in_router ip route replace default via "$CLIENT_IP"
in_client ip route replace default via "$ROUTER_IP"
# -i: without it `docker exec` hands nft an empty stdin, and `nft -f -` quietly loads nothing.
docker exec -i vibedpn-wg-server nft -f - <<EOF
table inet vibedpn_test {
  chain input {
    type filter hook input priority filter; policy accept;
    iifname "wg0" ip saddr $CLIENT_WG tcp dport $PROBE_PORT tcp flags syn counter comment "syn"
    iifname "wg0" tcp dport $PROBE_PORT tcp flags syn tcp option maxseg size > $CLAMPED_MSS counter comment "big"
  }
}
EOF
in_lan ping -c 2 -W 2 "$SERVER_WG" ||
  { echo "FAIL: the LAN host behind the router gets no replies through the gateway" >&2; exit 1; }
# Nothing listens on the port: the SYN arrives all the same, and that is all the counters need.
in_lan nc -w 2 "$SERVER_WG" "$PROBE_PORT" </dev/null >/dev/null 2>&1 || true
# A counter that cannot be read is a failure, never a zero: an empty value would let the MSS
# check pass for the wrong reason.
syn_count() {
  count="$(docker exec vibedpn-wg-server nft list table inet vibedpn_test |
    awk -v tag="\"$1\"" '$0 ~ tag { for (i = 1; i < NF; i++) if ($i == "packets") print $(i + 1) }')"
  case "$count" in
    '' | *[!0-9]*)
      echo "FAIL: cannot read the '$1' counter on the server" >&2
      exit 1
      ;;
  esac
  printf '%s\n' "$count"
}
syn="$(syn_count syn)"
big="$(syn_count big)"
if [ "$syn" -lt 1 ]; then
  echo "FAIL: no SYN of the LAN host reached the server as $CLIENT_WG" >&2
  exit 1
fi
if [ "$big" -ne 0 ]; then
  echo "FAIL: a SYN crossed the gateway with an MSS above $CLAMPED_MSS (tunnel MTU 1400)" >&2
  exit 1
fi
docker exec vibedpn-wg-server nft delete table inet vibedpn_test
# The split box is next door on the gateway network: directly the router reaches it, through the
# gateway it must not — the gateway forwards into wg0 and nowhere else.
in_router ping -c 1 -W 2 "$SPLIT_IP" >/dev/null
in_router ip route replace "$SPLIT_IP/32" via "$CLIENT_IP"
if in_router ping -c 1 -W 2 "$SPLIT_IP" >/dev/null 2>&1; then
  echo "FAIL: the gateway forwarded LAN traffic past the tunnel" >&2
  exit 1
fi
in_client ip route replace default via "$GATEWAY"
docker rm -f vibedpn-wg-lan vibedpn-wg-router >/dev/null
docker network rm "$LAN_NETWORK" >/dev/null

log "a peer added to a running server is applied without a restart"
extra_pub="$(awg_tool genkey | awg_tool pubkey)"
server_restarts="$(docker inspect -f '{{.RestartCount}}' vibedpn-wg-server)"
cp "$SRV_DIR/wg0.conf" "$WORK_DIR/srv-original.conf"
{
  cat "$WORK_DIR/srv-original.conf"
  printf '\n[Peer]\nPublicKey = %s\nAllowedIPs = %s/32\n' "$extra_pub" "$EXTRA_WG"
} >"$WORK_DIR/srv-extra.conf"
replace_server_conf "$WORK_DIR/srv-extra.conf"
await_server_peer present "$extra_pub"
docker exec vibedpn-wg-server ip route show dev wg0 | grep -q "^$EXTRA_WG "
same_restarts vibedpn-wg-server "$server_restarts"
in_client ping -c 1 -W 2 "$SERVER_WG" >/dev/null

log "removing it again drops the peer and its route, still without a restart"
replace_server_conf "$WORK_DIR/srv-original.conf"
await_server_peer absent "$extra_pub"
if docker exec vibedpn-wg-server ip route show dev wg0 | grep -q "^$EXTRA_WG "; then
  echo "FAIL: the route of a removed peer is still there" >&2
  exit 1
fi
same_restarts vibedpn-wg-server "$server_restarts"
in_client ping -c 1 -W 2 "$SERVER_WG" >/dev/null

# core renders a server with no peers as [Interface] only, and the first peer arrives after a
# blank line — which must not read as a changed interface. Same shape as wg-server.conf.j2.
log "an empty server gets its first peer and loses its last one without a restart"
EMPTY_DIR="$WORK_DIR/empty"
mkdir -m 700 "$EMPTY_DIR"
cat >"$WORK_DIR/empty-interface.conf" <<EOF
# VibeDPN WireGuard server, role vps. Rendered by core from config.yaml at every start;
# edits here are overwritten. The private key lives in server.key next to this file.
[Interface]
Address = $SERVER_WG/24
ListenPort = $LISTEN_PORT
PrivateKey = $server_key
$(awg_interface_keys)
EOF
{
  cat "$WORK_DIR/empty-interface.conf"
  printf '\n[Peer]\n# first\nPublicKey = %s\nAllowedIPs = %s/32\n' "$extra_pub" "$EXTRA_WG"
} >"$WORK_DIR/empty-first.conf"
cp "$WORK_DIR/empty-interface.conf" "$EMPTY_DIR/wg0.conf"
chmod 600 "$EMPTY_DIR/wg0.conf"
docker run -d --name vibedpn-wg-empty --network "$NETWORK" \
  --restart unless-stopped --cap-add NET_ADMIN --device "$TUN_DEVICE" \
  -v "$EMPTY_DIR:/etc/wireguard:ro" "$IMAGE" server >/dev/null
await_health vibedpn-wg-empty
empty_peers() {
  docker exec vibedpn-wg-empty awg show wg0 peers | grep -cxF "$extra_pub" || true
}
for step in first interface; do
  cp "$WORK_DIR/empty-$step.conf" "$EMPTY_DIR/.wg0.conf.new"
  chmod 600 "$EMPTY_DIR/.wg0.conf.new"
  mv "$EMPTY_DIR/.wg0.conf.new" "$EMPTY_DIR/wg0.conf"
  want=1
  [ "$step" = interface ] && want=0
  elapsed=0
  until [ "$(empty_peers)" = "$want" ]; do
    elapsed=$((elapsed + 2))
    if [ "$elapsed" -gt "$HANDSHAKE_TIMEOUT" ]; then
      echo "FAIL: the empty server did not apply '$step' in ${HANDSHAKE_TIMEOUT}s" >&2
      docker logs --tail 10 vibedpn-wg-empty >&2
      exit 1
    fi
    sleep 2
  done
  same_restarts vibedpn-wg-empty 0
done
docker rm -f vibedpn-wg-empty >/dev/null

log "a broken tunnel restarts the container instead of leaking"
in_client ip link set wg0 down
elapsed=0
while [ "$elapsed" -lt "$HANDSHAKE_TIMEOUT" ]; do
  restarts="$(docker inspect -f '{{.RestartCount}}' vibedpn-wg-client)"
  if [ "$restarts" -gt 0 ]; then
    break
  fi
  sleep 2
  elapsed=$((elapsed + 2))
done
if [ "$restarts" -eq 0 ]; then
  echo "FAIL: the client kept running with a downed tunnel" >&2
  exit 1
fi
await_health vibedpn-wg-client
in_client ping -c 1 -W 2 "$SERVER_WG"
fails in_client ping -c 1 -W 2 "$GATEWAY"

# The real wg-server runs with network_mode: host and shares the directory of its control socket
# with core. A container killed instead of stopped takes the daemon and its TUN interface with it,
# but the socket file stays in that directory, and an interface of the previous kernel-module image
# (a plain `wg0` of another type) can still be in the network namespace of the host. Like
# compose.yaml it mounts a directory for the config, so a file that core replaces by rename is
# visible inside.
log "a host-namespace server comes back after a crash that left a socket and a foreign wg0 behind"
HOST_DIR="$WORK_DIR/host"
HOST_SOCKET_DIR="$WORK_DIR/host-socket"
mkdir -m 700 "$HOST_DIR" "$HOST_SOCKET_DIR"
sed "s/^ListenPort = .*/ListenPort = $((LISTEN_PORT + 1))/" "$WORK_DIR/server.conf" \
  >"$HOST_DIR/wg0.conf"
chmod 600 "$HOST_DIR/wg0.conf"
docker run -d --name vibedpn-wg-host --network host --cap-add NET_ADMIN --device "$TUN_DEVICE" \
  -v "$HOST_DIR:/etc/wireguard:ro" -v "$HOST_SOCKET_DIR:$SOCKET_DIR" "$IMAGE" server >/dev/null
await_health vibedpn-wg-host
# core reads the peers through the socket from its own container, in the host namespace as well
docker run --rm --network host -v "$HOST_SOCKET_DIR:$SOCKET_DIR" --entrypoint awg "$IMAGE" \
  show wg0 dump | head -n 1 | grep -q "$(printf '\t')$((LISTEN_PORT + 1))$(printf '\t')" ||
  { echo "FAIL: another container cannot read the server through the shared socket" >&2; exit 1; }
docker kill -s KILL vibedpn-wg-host >/dev/null
[ -S "$HOST_SOCKET_DIR/wg0.sock" ] ||
  { echo "FAIL: no stale socket after the kill, so the test proves nothing" >&2; exit 1; }
docker run --rm --network host --cap-add NET_ADMIN --entrypoint ip "$IMAGE" link add wg0 type dummy
docker start vibedpn-wg-host >/dev/null
await_health vibedpn-wg-host
docker run --rm --network host --entrypoint ip "$IMAGE" -d link show wg0 | grep -q "tun" ||
  { echo "FAIL: wg0 is not the TUN interface of the daemon after the restart" >&2; exit 1; }

# After a reboot Docker restarts containers without waiting for core, so the server may start
# on the previous file; core then replaces it by rename, and the server has to notice.
log "a server rebuilds the tunnel when core replaces its config"
docker update --restart unless-stopped vibedpn-wg-host >/dev/null
NEW_PORT=$((LISTEN_PORT + 2))
sed "s/^ListenPort = .*/ListenPort = $NEW_PORT/" "$HOST_DIR/wg0.conf" >"$HOST_DIR/.wg0.conf.new"
chmod 600 "$HOST_DIR/.wg0.conf.new"
mv "$HOST_DIR/.wg0.conf.new" "$HOST_DIR/wg0.conf"
elapsed=0
port=""
while [ "$elapsed" -lt "$HANDSHAKE_TIMEOUT" ]; do
  port="$(docker exec vibedpn-wg-host awg show wg0 listen-port 2>/dev/null || true)"
  [ "$port" = "$NEW_PORT" ] && break
  sleep 2
  elapsed=$((elapsed + 2))
done
if [ "$port" != "$NEW_PORT" ]; then
  echo "FAIL: the server still listens on '$port' after its config changed to $NEW_PORT" >&2
  docker logs --tail 10 vibedpn-wg-host >&2
  exit 1
fi
if [ "$(docker inspect -f '{{.RestartCount}}' vibedpn-wg-host)" -eq 0 ]; then
  echo "FAIL: the port changed without a restart, so the watchdog was not what applied it" >&2
  exit 1
fi
docker rm -f vibedpn-wg-host >/dev/null

log "a stopped container exits cleanly"
docker stop -t 10 vibedpn-wg-client >/dev/null
state="$(docker inspect -f '{{.State.ExitCode}}' vibedpn-wg-client)"
if [ "$state" != 0 ]; then
  echo "FAIL: the client exited with $state on SIGTERM, expected a clean 0" >&2
  docker logs vibedpn-wg-client >&2
  exit 1
fi

# AmneziaWG with no obfuscation keys must be WireGuard on the wire. Both ends here are our daemon,
# so that is checked against a WireGuard that is not ours: wireguard-go from the Alpine packages.
if [ "$FLAVOR" = plain ]; then
  log "a plain file handshakes with vanilla WireGuard (wireguard-go), as a provider's server would"
  vanilla_key="$(awg_tool genkey)"
  vanilla_pub="$(printf '%s' "$vanilla_key" | awg_tool pubkey)"
  vc_key="$(awg_tool genkey)"
  vc_pub="$(printf '%s' "$vc_key" | awg_tool pubkey)"
  cat >"$WORK_DIR/vanilla.conf" <<EOF
[Interface]
PrivateKey = $vanilla_key
ListenPort = $LISTEN_PORT

[Peer]
PublicKey = $vc_pub
AllowedIPs = $VANILLA_CLIENT_WG/32
EOF
  cat >"$WORK_DIR/vanilla-client.conf" <<EOF
[Interface]
Address = $VANILLA_CLIENT_WG/32
PrivateKey = $vc_key

[Peer]
PublicKey = $vanilla_pub
Endpoint = $VANILLA_IP:$LISTEN_PORT
AllowedIPs = $VANILLA_WG/32
PersistentKeepalive = 25
EOF
  chmod 600 "$WORK_DIR/vanilla.conf" "$WORK_DIR/vanilla-client.conf"
  docker run -d --name vibedpn-wg-vanilla --network "$NETWORK" --ip "$VANILLA_IP" --cap-add NET_ADMIN \
    --device "$TUN_DEVICE" -v "$WORK_DIR/vanilla.conf:/vanilla.conf:ro" "$VANILLA_IMAGE" sh -c "
      apk add -q --no-cache wireguard-go wireguard-tools-wg iproute2 &&
      wireguard-go wg0 && wg setconf wg0 /vanilla.conf &&
      ip address add $VANILLA_WG/24 dev wg0 && ip link set wg0 up && exec sleep 3600" >/dev/null
  docker run -d --name vibedpn-wg-vanilla-client --network "$NETWORK" --ip "$VANILLA_CLIENT_IP" \
    --cap-add NET_ADMIN --device "$TUN_DEVICE" --sysctl net.ipv4.ip_forward=1 \
    --sysctl net.ipv4.conf.all.src_valid_mark=1 \
    -v "$WORK_DIR/vanilla-client.conf:/etc/wireguard/wg0.conf:ro" "$IMAGE" client >/dev/null
  elapsed=0
  until docker exec vibedpn-wg-vanilla-client ping -c 1 -W 2 "$VANILLA_WG" >/dev/null 2>&1; do
    sleep 2
    elapsed=$((elapsed + 2))
    # apk installs the packages before wireguard-go starts, which takes a few seconds
    if [ "$elapsed" -gt "$VANILLA_TIMEOUT" ]; then
      echo "FAIL: a plain file does not reach vanilla WireGuard" >&2
      docker logs --tail 10 vibedpn-wg-vanilla >&2
      docker logs --tail 10 vibedpn-wg-vanilla-client >&2
      exit 1
    fi
  done
  await_health vibedpn-wg-vanilla-client
  docker rm -f vibedpn-wg-vanilla vibedpn-wg-vanilla-client >/dev/null
fi

log "TUNNEL-OK"
