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
SERVER_WG=10.78.0.1
CLIENT_WG=10.78.0.2
SPLIT_WG=10.78.0.3
LISTEN_PORT=51820
WORK_DIR="$(mktemp -d)"
HANDSHAKE_TIMEOUT=30
OUTSIDE=8.8.8.8  # never reached: either the kill switch drops it or the tunnel has no exit

log() {
  echo "== $*"
}

cleanup() {
  docker rm -f vibedpn-wg-server vibedpn-wg-client vibedpn-wg-split vibedpn-wg-host \
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
# below depends on it.
docker run -d --name vibedpn-wg-server --network "$NETWORK" --ip "$SERVER_IP" \
  --restart unless-stopped --cap-add NET_ADMIN --sysctl net.ipv4.ip_forward=1 \
  -v "$WORK_DIR/server.conf:/etc/wireguard/wg0.conf:ro" "$IMAGE" server >/dev/null
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
