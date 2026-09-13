#!/bin/sh
# A real WireGuard tunnel between two vibedpn/wg containers: handshake, traffic through the
# tunnel, and the client kill switch (nothing leaves except the tunnel, even when it breaks).
#
# Needs a Linux host whose kernel has the wireguard module and a Docker daemon. The image is
# taken from VIBEDPN_WG_IMAGE (default: the tag the repository builds).
set -eu

IMAGE="${VIBEDPN_WG_IMAGE:-ghcr.io/borodatych/vibedpn-wg:test}"
NETWORK=vibedpn-wg-test
SUBNET=10.99.0.0/24
GATEWAY=10.99.0.1
SERVER_IP=10.99.0.2
CLIENT_IP=10.99.0.3
SPLIT_IP=10.99.0.4
LAN_IP=10.99.0.5
PROBE_PORT=8443
# The client file sets MTU 1400: an IPv4 SYN through it may carry at most 1400 - 40.
CLAMPED_MSS=1360
SERVER_WG=10.78.0.1
CLIENT_WG=10.78.0.2
SPLIT_WG=10.78.0.3
EXTRA_WG=10.78.0.9
LISTEN_PORT=51820
WORK_DIR="$(mktemp -d)"
HANDSHAKE_TIMEOUT=30
OUTSIDE=8.8.8.8  # never reached: either the kill switch drops it or the tunnel has no exit

log() {
  echo "== $*"
}

cleanup() {
  docker rm -f vibedpn-wg-server vibedpn-wg-client vibedpn-wg-split vibedpn-wg-host vibedpn-wg-empty vibedpn-wg-lan \
    >/dev/null 2>&1 || true
  # The host-namespace part of the test may leave wg0 behind; remove it without needing root.
  docker run --rm --network host --cap-add NET_ADMIN --entrypoint ip "$IMAGE" \
    link del wg0 >/dev/null 2>&1 || true
  docker network rm "$NETWORK" >/dev/null 2>&1 || true
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

wg_tool() {
  # -i: `wg pubkey` reads the key on stdin.
  docker run --rm -i --entrypoint wg "$IMAGE" "$@"
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

log "keys"
server_key="$(wg_tool genkey)"
client_key="$(wg_tool genkey)"
split_key="$(wg_tool genkey)"
server_pub="$(printf '%s' "$server_key" | wg_tool pubkey)"
client_pub="$(printf '%s' "$client_key" | wg_tool pubkey)"
split_pub="$(printf '%s' "$split_key" | wg_tool pubkey)"

cat >"$WORK_DIR/server.conf" <<EOF
[Interface]
Address = $SERVER_WG/24
ListenPort = $LISTEN_PORT
PrivateKey = $server_key

[Peer]
PublicKey = $client_pub
AllowedIPs = $CLIENT_WG/32

[Peer]
PublicKey = $split_pub
AllowedIPs = $SPLIT_WG/32
EOF

# A home box that only wants to reach the VPS, not to exit through it: no 0.0.0.0/0, and no
# PersistentKeepalive either — the entrypoint has to mark its packets and add the keepalive
# itself, or the kill switch would strangle the handshake.
cat >"$WORK_DIR/split.conf" <<EOF
[Interface]
Address = $SPLIT_WG/32
PrivateKey = $split_key

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
DNS = 10.78.0.1   # a wg-quick key that wg setconf must never see

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
  --restart unless-stopped --cap-add NET_ADMIN --sysctl net.ipv4.ip_forward=1 \
  -v "$SRV_DIR:/etc/wireguard:ro" "$IMAGE" server >/dev/null
docker run -d --name vibedpn-wg-client --network "$NETWORK" --ip "$CLIENT_IP" \
  --restart unless-stopped --cap-add NET_ADMIN --sysctl net.ipv4.ip_forward=1 \
  --sysctl net.ipv4.conf.all.src_valid_mark=1 \
  -v "$WORK_DIR/client.conf:/etc/wireguard/wg0.conf:ro" "$IMAGE" client >/dev/null
docker run -d --name vibedpn-wg-split --network "$NETWORK" --ip "$SPLIT_IP" \
  --restart unless-stopped --cap-add NET_ADMIN --sysctl net.ipv4.ip_forward=1 \
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
    if docker exec vibedpn-wg-server wg show wg0 peers | grep -qxF "$2"; then
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
docker exec vibedpn-wg-server wg show wg0 latest-handshakes

log "a split tunnel handshakes too: the kill switch must not strangle its own packets"
await_health vibedpn-wg-split
docker exec vibedpn-wg-split ping -c 2 -W 2 "$SERVER_WG"
docker exec vibedpn-wg-split wg show wg0 persistent-keepalive | grep -q 25
if docker exec vibedpn-wg-split ip route show table "$LISTEN_PORT" | grep -q default; then
  echo "FAIL: a split tunnel must not take over the default route" >&2
  exit 1
fi

log "traffic through the tunnel"
in_client ping -c 2 -W 2 "$SERVER_WG"
docker exec vibedpn-wg-server ping -c 2 -W 2 "$CLIENT_WG"

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

log "the client is a gateway: another host routes through it into the tunnel"
# A LAN host with no WireGuard of its own and the client as its default gateway — the way core
# steers LAN traffic to 10.77.0.10. It reaches the server only through the client, masqueraded
# as the client's tunnel address (the server's AllowedIPs for it is a /32).
docker run -d --name vibedpn-wg-lan --network "$NETWORK" --ip "$LAN_IP" --cap-add NET_ADMIN \
  --entrypoint sleep "$IMAGE" 600 >/dev/null
in_lan() {
  docker exec vibedpn-wg-lan "$@"
}
in_lan ip route replace default via "$CLIENT_IP"
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
in_lan ping -c 2 -W 2 "$SERVER_WG"
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
# The split box is next door on the bridge: directly it answers, through the gateway it must not —
# the gateway forwards into wg0 and nowhere else.
in_lan ping -c 1 -W 2 "$SPLIT_IP" >/dev/null
in_lan ip route replace "$SPLIT_IP/32" via "$CLIENT_IP"
if in_lan ping -c 1 -W 2 "$SPLIT_IP" >/dev/null 2>&1; then
  echo "FAIL: the gateway forwarded LAN traffic past the tunnel" >&2
  exit 1
fi
docker rm -f vibedpn-wg-lan >/dev/null

log "a peer added to a running server is applied without a restart"
extra_pub="$(wg_tool genkey | wg_tool pubkey)"
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
EOF
{
  cat "$WORK_DIR/empty-interface.conf"
  printf '\n[Peer]\n# first\nPublicKey = %s\nAllowedIPs = %s/32\n' "$extra_pub" "$EXTRA_WG"
} >"$WORK_DIR/empty-first.conf"
cp "$WORK_DIR/empty-interface.conf" "$EMPTY_DIR/wg0.conf"
chmod 600 "$EMPTY_DIR/wg0.conf"
docker run -d --name vibedpn-wg-empty --network "$NETWORK" \
  --restart unless-stopped --cap-add NET_ADMIN \
  -v "$EMPTY_DIR:/etc/wireguard:ro" "$IMAGE" server >/dev/null
await_health vibedpn-wg-empty
empty_peers() {
  docker exec vibedpn-wg-empty wg show wg0 peers | grep -cxF "$extra_pub" || true
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

# The real wg-server runs with network_mode: host, so its interface outlives a container that
# was killed instead of stopped — exactly what happens on a crash or a docker kill. Like
# compose.yaml it mounts a directory, so a file that core replaces by rename is visible inside.
log "a host-namespace server comes back after a crash that left wg0 behind"
HOST_DIR="$WORK_DIR/host"
mkdir -m 700 "$HOST_DIR"
sed "s/^ListenPort = .*/ListenPort = $((LISTEN_PORT + 1))/" "$WORK_DIR/server.conf" \
  >"$HOST_DIR/wg0.conf"
chmod 600 "$HOST_DIR/wg0.conf"
docker run -d --name vibedpn-wg-host --network host --cap-add NET_ADMIN \
  -v "$HOST_DIR:/etc/wireguard:ro" "$IMAGE" server >/dev/null
await_health vibedpn-wg-host
docker kill -s KILL vibedpn-wg-host >/dev/null
if ! docker run --rm --network host --cap-add NET_ADMIN --entrypoint ip "$IMAGE" \
  link show wg0 >/dev/null 2>&1; then
  echo "FAIL: wg0 vanished with the killed container, so the test proves nothing" >&2
  exit 1
fi
docker start vibedpn-wg-host >/dev/null
await_health vibedpn-wg-host

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
  port="$(docker exec vibedpn-wg-host wg show wg0 listen-port 2>/dev/null || true)"
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

log "TUNNEL-OK"
