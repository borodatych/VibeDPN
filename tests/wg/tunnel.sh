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
SERVER_WG=10.78.0.1
CLIENT_WG=10.78.0.2
LISTEN_PORT=51820
WORK_DIR="$(mktemp -d)"
HANDSHAKE_TIMEOUT=30
OUTSIDE=8.8.8.8  # never reached: either the kill switch drops it or the tunnel has no exit

log() {
  echo "== $*"
}

cleanup() {
  docker rm -f vibedpn-wg-server vibedpn-wg-client >/dev/null 2>&1 || true
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
  # The command must fail; used for the leak checks, where success is the defect.
  if "$@" >/dev/null 2>&1; then
    echo "FAIL: '$*' succeeded, but the kill switch had to drop it" >&2
    exit 1
  fi
}

log "keys"
server_key="$(wg_tool genkey)"
client_key="$(wg_tool genkey)"
server_pub="$(printf '%s' "$server_key" | wg_tool pubkey)"
client_pub="$(printf '%s' "$client_key" | wg_tool pubkey)"

cat >"$WORK_DIR/server.conf" <<EOF
[Interface]
Address = $SERVER_WG/24
ListenPort = $LISTEN_PORT
PrivateKey = $server_key

[Peer]
PublicKey = $client_pub
AllowedIPs = $CLIENT_WG/32
EOF

# Tabs, an "=" without spaces and a comment: the entrypoint has to read a config the way
# WireGuard does, not the way a single example happens to be formatted.
cat >"$WORK_DIR/client.conf" <<EOF
[Interface]
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

await_client_health() {
  elapsed=0
  while [ "$elapsed" -lt "$HANDSHAKE_TIMEOUT" ]; do
    if in_client /usr/local/bin/entrypoint.sh health >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  echo "FAIL: the client was not healthy within ${HANDSHAKE_TIMEOUT}s" >&2
  docker logs vibedpn-wg-client >&2
  docker logs vibedpn-wg-server >&2
  exit 1
}

log "handshake"
await_client_health
in_client /usr/local/bin/entrypoint.sh health
docker exec vibedpn-wg-server /usr/local/bin/entrypoint.sh health
docker exec vibedpn-wg-server wg show wg0 latest-handshakes

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
await_client_health
in_client ping -c 1 -W 2 "$SERVER_WG"
fails in_client ping -c 1 -W 2 "$GATEWAY"

log "a stopped container exits cleanly"
docker stop -t 10 vibedpn-wg-client >/dev/null
state="$(docker inspect -f '{{.State.ExitCode}}' vibedpn-wg-client)"
if [ "$state" != 0 ]; then
  echo "FAIL: the client exited with $state on SIGTERM, expected a clean 0" >&2
  docker logs vibedpn-wg-client >&2
  exit 1
fi

log "TUNNEL-OK"
