#!/bin/sh
# E2E stand of a home box: every service of the role on one Linux host with Docker, and no loop —
# the node's own traffic leaves directly even while the LAN is steered into an uplink.
#
# What runs is the product: `vibedpn init --role home`, `up`, `status`, `doctor`, the core and panel
# images of the repository, the pinned Mysterium node and consumer, AdGuard Home and Postgres. The
# LAN is a bridge lan0 (box 192.168.77.1), so AdGuard never meets a DNS server of the host itself.
# routing.mode full through dpn: LAN traffic is marked for the consumer gateway (no session yet,
# which is Stage 8), while myst-provider sits on its own Docker bridge and must reach the internet
# with the same address as the host.
#
# Needs: Linux, Docker Engine >= 28, the wireguard module, sudo, curl, python3 (or a python with the
# CLI installed in VIBEDPN_E2E_PYTHON), the internet, images ghcr.io/borodatych/vibedpn-core:$TAG
# and ghcr.io/borodatych/vibedpn-ui:$TAG-full. VIBEDPN_E2E_EXIT_URL: an echo service of the exit
# address (default https://api.ipify.org, the one `doctor --network` uses).
set -eu

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
TAG="${VIBEDPN_TAG:-e2e}"
CORE_IMAGE="ghcr.io/borodatych/vibedpn-core:$TAG"
UI_IMAGE="ghcr.io/borodatych/vibedpn-ui:$TAG-full"
CONSUMER_IMAGE="ghcr.io/borodatych/vibedpn-myst-consumer:$TAG"
EXIT_URL="${VIBEDPN_E2E_EXIT_URL:-https://api.ipify.org}"
WORK="$(mktemp -d)"
BOX="$WORK/box"
PASSWORD=e2e-home-123
LAN=lan0
LAN_SUBNET=192.168.77.0/24
BOX_LAN_IP=192.168.77.1
DEVICE_IP=192.168.77.2
NETNS=e2e-homelan
TIMEOUT=300
ISP_COMMENT=e2e-home-isp

log() {
  echo "== $*"
}

# The ISP router of a real home LAN NATs the LAN subnet; the stand's LAN is unknown upstream, so the
# host plays that router. Without it a leak around the tunnel would look like a working kill switch.
isp_nat() {
  # $1: -A to add, -D to delete. NAT of the LAN subnet out of the WAN, and the transit Docker's
  # forward drop would kill: a real one-port box has LAN and WAN on one interface, the stand does not.
  wan="$(ip route show default | awk 'NR == 1 { print $5 }')"
  sudo iptables-nft -t nat "$1" POSTROUTING -s "$LAN_SUBNET" -o "$wan" \
    -m comment --comment "$ISP_COMMENT" -j MASQUERADE
  if [ "$1" = -A ]; then action=-I; else action="$1"; fi
  sudo iptables-nft "$action" DOCKER-USER -i "$LAN" -o "$wan" \
    -m comment --comment "$ISP_COMMENT" -j ACCEPT
  sudo iptables-nft "$action" DOCKER-USER -i "$wan" -o "$LAN" \
    -m conntrack --ctstate RELATED,ESTABLISHED -m comment --comment "$ISP_COMMENT" -j ACCEPT
}

cleanup() {
  if [ -n "${CLI:-}" ] && [ -f "$BOX/config.yaml" ]; then
    sudo "$CLI" down --dir "$BOX" >/dev/null 2>&1 || true
  fi
  if [ -n "${PY:-}" ] && [ -x "$PY" ]; then
    sudo "$PY" -c "from vibedpn.engine.router import remove_router; remove_router()" >/dev/null 2>&1 || true
  fi
  isp_nat -D 2>/dev/null || true
  sudo ip netns del "$NETNS" 2>/dev/null || true
  sudo ip link del "$LAN" 2>/dev/null || true
  sudo rm -rf "$WORK"
}
trap cleanup EXIT

fail() {
  echo "FAIL: $*" >&2
  {
    echo "--- diagnostics"
    echo "# containers"; docker ps -a --filter name=vibedpn- --format '{{.Names}} {{.Status}}'
    echo "# core"; docker logs --tail 25 vibedpn-core-1
    echo "# myst-provider"; docker logs --tail 15 vibedpn-myst-provider-1
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
docker image inspect "$CORE_IMAGE" "$UI_IMAGE" "$CONSUMER_IMAGE" >/dev/null 2>&1 ||
  fail "build $CORE_IMAGE, $UI_IMAGE and $CONSUMER_IMAGE first (core, --build-arg UI_VARIANT=full ui, images/myst-consumer)"

# --- the LAN ------------------------------------------------------------------------------------
log "stand: the LAN bridge and a device behind the box"
sudo ip link add "$LAN" type bridge
sudo ip addr add "$BOX_LAN_IP/24" dev "$LAN"
sudo ip link set "$LAN" up
sudo ip netns add "$NETNS"
sudo ip link add e2e-hdev type veth peer name e2e-hlan
sudo ip link set e2e-hlan master "$LAN" up
sudo ip link set e2e-hdev netns "$NETNS"
sudo ip netns exec "$NETNS" ip addr add "$DEVICE_IP/24" dev e2e-hdev
sudo ip netns exec "$NETNS" ip link set e2e-hdev up
sudo ip netns exec "$NETNS" ip link set lo up
sudo ip netns exec "$NETNS" ip route add default via "$BOX_LAN_IP"
isp_nat -A

# --- the box ------------------------------------------------------------------------------------
log "box: role home, LAN on $LAN, panel full, routing full through dpn"
mkdir "$BOX"
cp "$REPO/compose.yaml" "$BOX/"
printf '%s\n' "$PASSWORD" >"$WORK/password"
sudo "$CLI" init --dir "$BOX" --role home --ui-variant full --password-file "$WORK/password" >/dev/null
sudo sed -i \
  -e "s/^  lan_interface: .*/  lan_interface: $LAN/" \
  -e "s#^  lan_subnet: .*#  lan_subnet: $LAN_SUBNET#" \
  -e "s/^  lan_address: .*/  lan_address: $BOX_LAN_IP/" \
  -e "s/^  mode: off$/  mode: full/" \
  "$BOX/config.yaml"
sudo sed -i "s/^VIBEDPN_TAG=.*/VIBEDPN_TAG=$TAG/" "$BOX/.env"
grep -q "^COMPOSE_PROFILES=provider,consumer,router,dns,ui$" "$BOX/.env" ||
  fail "init --role home did not enable provider, consumer, router, dns and ui"

sudo "$CLI" up --dir "$BOX" >/dev/null 2>&1 || fail "vibedpn up failed"

log "every service of the role comes up"
settled() {
  for name in core adguard myst-provider myst-consumer ui-db ui; do
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
  [ "$i" -lt "$TIMEOUT" ] || fail "the services of role home did not all come up in $TIMEOUT s"
  sleep 5
done
docker ps --filter name=vibedpn- --format '{{.Names}}: {{.Status}}'

log "no loop: the node leaves directly while the LAN is steered into dpn"
# nft prints the mark zero-padded (0x00000020)
sudo nft list table inet vibedpn_router | grep -qE "meta mark set 0x0*20" ||
  fail "routing.mode full does not mark the LAN for uplink dpn"
host_exit="$(curl -s --max-time 15 "$EXIT_URL" || true)"
[ -n "$host_exit" ] || fail "the host itself gets no answer from $EXIT_URL"
node_exit="$(docker exec vibedpn-myst-provider-1 wget -qO- -T 15 "$EXIT_URL" 2>/dev/null || true)"
[ "$node_exit" = "$host_exit" ] ||
  fail "myst-provider leaves as '${node_exit:-nothing}', the host as $host_exit: the node's traffic is not direct"
echo "host and node both leave as $host_exit"

log "kill switch of dpn: a LAN device has no exit while the consumer has no session"
# The device resolves nothing itself: the name of the echo service is resolved on the host.
exit_host="$(printf '%s' "$EXIT_URL" | sed -E 's#^[a-z]+://([^/:]+).*#\1#')"
exit_ip="$(getent ahostsv4 "$exit_host" | awk 'NR == 1 { print $1 }')"
[ -n "$exit_ip" ] || fail "cannot resolve $exit_host on the host"
device_exit() {
  sudo ip netns exec "$NETNS" curl -s --max-time 10 --resolve "$exit_host:443:$exit_ip" "$EXIT_URL" 2>/dev/null || true
}
# First prove the path works: policy bypass sends the device direct, through the ISP NAT.
"$CLI" device set "$DEVICE_IP" bypass --dir "$BOX" >/dev/null || fail "vibedpn device set bypass failed"
i=0
until [ "$(device_exit)" = "$host_exit" ]; do
  i=$((i + 5))
  [ "$i" -lt 60 ] || fail "with policy bypass the LAN device does not reach $EXIT_URL: the stand's LAN path is broken"
  sleep 5
done
echo "bypass: the LAN device leaves as the host"
"$CLI" device unset "$DEVICE_IP" --dir "$BOX" >/dev/null || fail "vibedpn device unset failed"
sleep 5
leaked="$(device_exit)"
[ -z "$leaked" ] ||
  fail "the LAN device leaves as $leaked through myst-consumer without a session: traffic bypasses the dpn tunnel"
echo "routing full through dpn without a session: the LAN device has no exit"

log "switching the mode never cuts a bypass device"
routing_put() {
  curl -s -o /dev/null -w '%{http_code}' -X PUT -H 'Content-Type: application/json' \
    -d "{\"mode\":\"$1\"}" "http://127.0.0.1:4480/routing"
}
"$CLI" device set "$DEVICE_IP" bypass --dir "$BOX" >/dev/null || fail "vibedpn device set bypass failed"
i=0
until [ "$(device_exit)" = "$host_exit" ]; do
  i=$((i + 5))
  [ "$i" -lt 60 ] || fail "with policy bypass the LAN device lost its exit"
  sleep 5
done
: >"$WORK/bypass-probes"
(
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
    # an empty answer is written as an empty line: a lost probe must count
    printf '%s\n' "$(device_exit)" >>"$WORK/bypass-probes"
    sleep 1
  done
) &
probes=$!
sleep 2
[ "$(routing_put off)" = 200 ] || fail "PUT /routing mode off failed"
sleep 3
[ "$(routing_put full)" = 200 ] || fail "PUT /routing mode full failed"
wait "$probes"
lost="$(grep -cvx "$host_exit" "$WORK/bypass-probes" || true)"
[ "$lost" = 0 ] || fail "the bypass device lost its exit in $lost of 12 probes while the mode switched"
echo "12 probes across off and back to full: the bypass device never lost its exit"
"$CLI" device unset "$DEVICE_IP" --dir "$BOX" >/dev/null || fail "vibedpn device unset failed"

log "TequilAPI of the consumer: core reaches it, the LAN does not"
i=0
until curl -s --max-time 5 "http://127.0.0.1:4480/status" | grep -q '"identity":"0x'; do
  i=$((i + 5))
  [ "$i" -lt 120 ] || fail "core did not create the consumer identity through TequilAPI (GET /status has no dpn identity)"
  sleep 5
done
curl -s --max-time 5 "http://127.0.0.1:4480/status" | grep -o '"dpn":{[^}]*}'
if sudo ip netns exec "$NETNS" curl -s -o /dev/null --max-time 5 "http://10.77.0.20:4050/healthcheck"; then
  fail "a LAN device reaches TequilAPI of the consumer"
fi
echo "TequilAPI: core yes, the LAN device no"

log "status and doctor"
sudo "$CLI" status --dir "$BOX" | grep -q "^uplink dpn: gateway" || fail "vibedpn status does not show uplink dpn"
sudo "$CLI" doctor --dir "$BOX" | grep -q "\[ ok \] router" || fail "doctor does not confirm the router"

log "memory of the role (informational)"
docker ps -q --filter name=vibedpn- | xargs docker stats --no-stream --format '{{.Name}} {{.MemUsage}}'

log "home stand passed"
