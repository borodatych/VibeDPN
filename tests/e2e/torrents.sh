#!/bin/sh
# E2E stand of the torrent client: Transmission as a service of a home box, driven the way the
# panel drives it — through the API of core. One Linux host with Docker, no uplink and no internet
# beyond pulling the image: the torrent added is a .torrent file made here, and nothing needs a peer.
#
# What runs is the product: `vibedpn init --role home --torrents`, `up`, `doctor`, `torrents`, the
# core image of the repository and the pinned linuxserver/transmission image. Checked: the RPC listens
# on 127.0.0.1 only and wants its password, the client runs as its own uid, core lists, adds, stops,
# limits and removes torrents, `doctor` is green, a disk that is not there stops the client and not
# the box, and `torrents disable` takes the container away and leaves the downloads.
#
# Needs: Linux, Docker Engine >= 28, sudo, curl, python3 (or a python with the CLI installed in
# VIBEDPN_E2E_PYTHON), the image ghcr.io/borodatych/vibedpn-core:$TAG, and the internet once for the
# image of Transmission.
set -eu

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
TAG="${VIBEDPN_TAG:-e2e}"
CORE_IMAGE="ghcr.io/borodatych/vibedpn-core:$TAG"
WORK="$(mktemp -d)"
BOX="$WORK/box"
DOWNLOADS="$WORK/downloads"
PASSWORD=e2e-torrents-123
LAN=lan0
LAN_SUBNET=192.168.77.0/24
BOX_LAN_IP=192.168.77.1
API=http://127.0.0.1:4480
RPC_PORT=9091
CLIENT_UID=7756
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
    echo "# transmission"; docker logs --tail 25 vibedpn-transmission-1
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
docker image inspect "$CORE_IMAGE" >/dev/null 2>&1 || fail "build $CORE_IMAGE first (docker build core)"

# --- the box ------------------------------------------------------------------------------------
log "stand: a LAN bridge for the address of the box"
sudo ip link add "$LAN" type bridge
sudo ip addr add "$BOX_LAN_IP/24" dev "$LAN"
sudo ip link set "$LAN" up

log "box: role home without a node, an uplink or a panel; the torrent client on"
mkdir "$BOX" "$DOWNLOADS"
cp "$REPO/compose.yaml" "$BOX/"
printf '%s\n' "$PASSWORD" >"$WORK/password"
sudo "$CLI" init --dir "$BOX" --role home --ui-variant lite --torrents --password-file "$WORK/password" >/dev/null
sudo "$PY" - "$BOX/config.yaml" "$LAN" "$LAN_SUBNET" "$BOX_LAN_IP" "$DOWNLOADS" <<'PYEOF'
import re
import sys

path, lan, subnet, address, downloads = sys.argv[1:]
text = open(path, encoding="utf-8").read()
for pattern, value in (
    (r"(?m)^  lan_interface: .*", f"  lan_interface: {lan}"),
    (r"(?m)^  lan_subnet: .*", f"  lan_subnet: {subnet}"),
    (r"(?m)^  lan_address: .*", f"  lan_address: {address}"),
    (r"(?m)^  download_dir: .*", f"  download_dir: {downloads}"),
    (r"(?m)^(provider:\n  enabled:) true", r"\1 false"),
    (r"(?m)^(  dpn:\n    enabled:) true", r"\1 false"),
    (r"(?m)^(dns:\n  enabled:) true", r"\1 false"),
    (r"(?m)^(ui:\n  enabled:) true", r"\1 false"),
):
    text, count = re.subn(pattern, value, text)
    assert count == 1, pattern
open(path, "w", encoding="utf-8").write(text)
PYEOF
sudo sed -i "s/^VIBEDPN_TAG=.*/VIBEDPN_TAG=$TAG/" "$BOX/.env"
sudo "$CLI" up --dir "$BOX" >/dev/null 2>&1 || fail "vibedpn up failed"
grep -q "^COMPOSE_PROFILES=.*torrents" "$BOX/.env" || fail "the torrents profile is not in .env"

log "the client comes up, and core answers for it"
settled() {
  status="$(docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' vibedpn-transmission-1 2>/dev/null || echo missing)"
  [ "$status" = "running healthy" ] || return 1
  curl -sf -o /dev/null "$API/torrents"
}
i=0
until settled; do
  i=$((i + 5))
  [ "$i" -lt "$TIMEOUT" ] || fail "the torrent client did not come up in $TIMEOUT s"
  sleep 5
done

log "the RPC listens on 127.0.0.1 only, and asks for its password"
listening="$(ss -ltnH "sport = :$RPC_PORT" | awk '{ print $4 }')"
[ "$listening" = "127.0.0.1:$RPC_PORT" ] || fail "the RPC listens on '$listening', not on 127.0.0.1 alone"
code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$RPC_PORT/transmission/rpc")"
[ "$code" = 401 ] || fail "the RPC answers $code without a password, not 401"

log "the client runs as its own uid, the one the router steers"
# the container shares the PID space of the host Docker runs on, so the host sees the daemon
uid="$(ps -C transmission-daemon -o uid= | head -1 | tr -d ' ')"
[ "$uid" = "$CLIENT_UID" ] || fail "transmission-daemon runs as uid '$uid', not as $CLIENT_UID"
[ -d "$DOWNLOADS/complete" ] && [ -d "$DOWNLOADS/incomplete" ] || fail "the download folders were not made"

log "a torrent made here is added through core and shows in the list"
"$PY" - "$WORK/probe.json" <<'PYEOF'
import base64
import hashlib
import json
import sys


def bencode(value):
    if isinstance(value, int):
        return b"i%de" % value
    if isinstance(value, str):
        value = value.encode()
    if isinstance(value, bytes):
        return b"%d:%s" % (len(value), value)
    if isinstance(value, list):
        return b"l" + b"".join(bencode(item) for item in value) + b"e"
    return b"d" + b"".join(bencode(k) + bencode(value[k]) for k in sorted(value)) + b"e"


data = bytes(range(256)) * 64
info = {"name": "e2e-probe.bin", "length": len(data), "piece length": 16384,
        "pieces": hashlib.sha1(data).digest()}
raw = bencode({"announce": "http://127.0.0.1:1/announce", "info": info})
json.dump({"torrent": base64.b64encode(raw).decode(), "subdir": "e2e", "paused": True},
          open(sys.argv[1], "w"))
PYEOF
code="$(curl -s -o "$WORK/added.json" -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
  -d @"$WORK/probe.json" "$API/torrents")"
[ "$code" = 201 ] || fail "adding a torrent answered $code: $(cat "$WORK/added.json")"
HASH="$("$PY" -c "import json,sys; print(json.load(open(sys.argv[1]))['id'])" "$WORK/added.json")"
curl -sf "$API/torrents" | grep -q "e2e-probe.bin" || fail "the torrent is not in the list"
curl -sf "$API/torrents/$HASH" | grep -q "$DOWNLOADS/complete/e2e" ||
  fail "the torrent does not go to the folder asked, on the host's path"
code="$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
  -d @"$WORK/probe.json" "$API/torrents")"
[ "$code" = 200 ] || fail "adding the same torrent again answered $code, not 200 (a duplicate)"

log "start, stop, a limit, and the storage page"
[ "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API/torrents/$HASH/start")" = 204 ] || fail "start failed"
[ "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API/torrents/$HASH/stop")" = 204 ] || fail "stop failed"
# the client stops a torrent on its next tick, not inside the call
i=0
until detail="$(curl -sf "$API/torrents/$HASH")" && echo "$detail" | grep -q '"status":"stopped"'; do
  i=$((i + 1))
  [ "$i" -lt 20 ] || fail "the torrent is not stopped: $detail"
  sleep 1
done
curl -sf -X PUT -H 'Content-Type: application/json' \
  -d '{"speed_limit_down":500,"speed_limit_down_enabled":true}' "$API/torrents/session" |
  grep -q '"speed_limit_down":500' || fail "the speed limit was not set"
grep -q "^  speed_limit_down: 500" "$BOX/config.yaml" || fail "the limit did not reach config.yaml"
curl -sf "$API/torrents/storage" | grep -q "\"download_dir\":\"$DOWNLOADS\"" ||
  fail "the storage page does not name the download folder"

log "doctor is green for the client"
doctor="$(sudo "$CLI" doctor --dir "$BOX" 2>&1 || true)"
echo "$doctor" | grep -E "torrents" || true
echo "$doctor" | grep -q "^\[ ok \] torrents rpc" || fail "doctor does not find the RPC answering"
echo "$doctor" | grep -q "^\[ ok \] torrents folder" || fail "doctor does not find the folder writable"
echo "$doctor" | grep -q "^\[ ok \] torrents space" || fail "doctor does not find enough space"
echo "$doctor" | grep -q "^\[FAIL\] torrents" && fail "doctor fails a check of the client"

log "a second up changes nothing: the limit set through the API is the file's too"
before="$(docker inspect -f '{{.State.StartedAt}}' vibedpn-transmission-1)"
sudo "$CLI" up --dir "$BOX" >/dev/null 2>&1 || fail "the second vibedpn up failed"
[ "$(docker inspect -f '{{.State.StartedAt}}' vibedpn-transmission-1)" = "$before" ] ||
  fail "the second up restarted the client"

log "remove with the data, then switch the client off: the container goes, the downloads stay"
[ "$(curl -s -o /dev/null -w '%{http_code}' -X DELETE "$API/torrents/$HASH?data=true")" = 204 ] || fail "remove failed"
curl -sf "$API/torrents" | grep -q "e2e-probe.bin" && fail "the torrent is still listed"
sudo "$CLI" torrents disable --dir "$BOX" >/dev/null
sudo "$CLI" up --dir "$BOX" >/dev/null 2>&1 || fail "vibedpn up after disable failed"
[ -z "$(docker ps -aq --filter name=vibedpn-transmission-1)" ] || fail "the client container is still there"
[ -d "$DOWNLOADS/complete" ] || fail "the downloads were taken away"
# core is recreated by this up (torrents.enabled is part of its fingerprint): wait for it to answer
i=0
until [ "$(curl -s -o /dev/null -w '%{http_code}' "$API/torrents")" = 503 ]; do
  i=$((i + 2))
  [ "$i" -lt 60 ] || fail "core does not say 503 for a client that is off"
  sleep 2
done

echo "PASS: torrents"
