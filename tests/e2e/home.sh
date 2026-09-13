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
EXIT_URL="${VIBEDPN_E2E_EXIT_URL:-https://api.ipify.org}"
WORK="$(mktemp -d)"
BOX="$WORK/box"
PASSWORD=e2e-home-123
LAN=lan0
LAN_SUBNET=192.168.77.0/24
BOX_LAN_IP=192.168.77.1
TIMEOUT=300

log() {
  echo "== $*"
}

cleanup() {
  if [ -n "${CLI:-}" ] && [ -f "$BOX/config.yaml" ]; then
    sudo "$CLI" down --dir "$BOX" >/dev/null 2>&1 || true
  fi
  if [ -n "${PY:-}" ] && [ -x "$PY" ]; then
    sudo "$PY" -c "from vibedpn.engine.router import remove_router; remove_router()" >/dev/null 2>&1 || true
  fi
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
docker image inspect "$CORE_IMAGE" "$UI_IMAGE" >/dev/null 2>&1 ||
  fail "build $CORE_IMAGE and $UI_IMAGE first (docker build -t ... core / --build-arg UI_VARIANT=full ui)"

# --- the LAN ------------------------------------------------------------------------------------
log "stand: the LAN bridge"
sudo ip link add "$LAN" type bridge
sudo ip addr add "$BOX_LAN_IP/24" dev "$LAN"
sudo ip link set "$LAN" up

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

log "status and doctor"
sudo "$CLI" status --dir "$BOX" | grep -q "^uplink dpn: gateway" || fail "vibedpn status does not show uplink dpn"
sudo "$CLI" doctor --dir "$BOX" | grep -q "\[ ok \] router" || fail "doctor does not confirm the router"

log "memory of the role (informational)"
docker ps -q --filter name=vibedpn- | xargs docker stats --no-stream --format '{{.Name}} {{.MemUsage}}'

log "home stand passed"
