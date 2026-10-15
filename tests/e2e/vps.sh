#!/bin/sh
# E2E stand of a bare VPS: the host is the VPS, and what runs on it is the product itself —
# `vibedpn init --role vps --no-provider --access`, `up`, `peer add`, `access add`, `doctor`.
# No Mysterium node, no panel, no password: an AmneziaWG server for the owner's own devices and a
# VLESS/REALITY access server.
#
# Around the VPS the stand builds, without the real internet:
#   - network e2e-vps-net (198.18.0.0/24, RFC 2544 benchmark range, bridge e2evps0): the host is
#     198.18.0.1 and is the public address of the VPS (the endpoint of the tunnel and the links);
#     a web container at 198.18.0.10 answers with the address it sees — the exit address;
#   - network e2e-vps-phones (198.19.0.0/24, bridge e2evps1) with the devices of the owner, away
#     from the web server: a device on its subnet would reach it on-link, around the tunnel;
#   - a "phone": vibedpn/wg in mode client, built from the file `vibedpn peer add` hands out, at
#     198.19.0.70, with its own kill switch: it has no way out except the tunnel;
#   - a "person" of the access server: the official xray with the link `vibedpn access add` made.
# So "through the VPS" is an address (the host, 198.18.0.1: the NAT of the tunnel egress) and not a
# guess from counters, and a phone without the obfuscation keys never handshakes: the proof that
# the keys act on the wire.
#
# REALITY borrows the handshake of a real site, so the access server needs the internet:
# VIBEDPN_E2E_OFFLINE=1 turns it off again after init (the flag is still checked) and skips the
# person; everything else runs.
#
# Needs: Linux, Docker Engine >= 28, /dev/net/tun, sudo, curl, python3 (or a python with the CLI
# installed in VIBEDPN_E2E_PYTHON), images ghcr.io/borodatych/vibedpn-{core,wg,xray}:$VIBEDPN_TAG.
set -eu

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
TAG="${VIBEDPN_TAG:-e2e}"
WG_IMAGE="ghcr.io/borodatych/vibedpn-wg:$TAG"
CORE_IMAGE="ghcr.io/borodatych/vibedpn-core:$TAG"
XRAY_IMAGE_OF_BOX="ghcr.io/borodatych/vibedpn-xray:$TAG"
PERSON_IMAGE=ghcr.io/xtls/xray-core:26.3.27
OFFLINE="${VIBEDPN_E2E_OFFLINE:-0}"
WORK="$(mktemp -d)"
BOX="$WORK/box"

INTERNET=e2e-vps-net
INTERNET_BRIDGE=e2evps0
INTERNET_SUBNET=198.18.0.0/24
VPS_PUBLIC=198.18.0.1
WEB=e2e-vps-web
WEB_IP=198.18.0.10
WEB_PORT=8080
PHONE=e2e-vps-phone
PHONES=e2e-vps-phones
PHONES_BRIDGE=e2evps1
PHONES_SUBNET=198.19.0.0/24
PHONES_GATEWAY=198.19.0.1
PHONE_IP=198.19.0.70
PLAIN=e2e-vps-plain
PLAIN_IP=198.19.0.71
PERSON=e2e-vps-person
PERSON_SOCKS=18080
TIMEOUT=60
# A phone without the obfuscation keys gets this long to prove it cannot handshake
MISMATCH_SECONDS=20

log() {
  echo "== $*"
}

cleanup() {
  if [ -n "${CLI:-}" ] && [ -f "$BOX/config.yaml" ]; then
    sudo "$CLI" down --dir "$BOX" >/dev/null 2>&1 || true
  fi
  # `down` stops core and leaves the firewall and the tunnel egress of the host as they were. The
  # stand is not a box: both go through the same code that applies them.
  if [ -n "${PY:-}" ] && [ -x "$PY" ]; then
    sudo "$PY" -c "
from vibedpn.config import Config
from vibedpn.engine.router import apply_tunnel_egress, remove_firewall
remove_firewall()
apply_tunnel_egress(Config.model_validate({
    'version': 1, 'role': 'home',
    'network': {'lan_interface': 'lo', 'lan_subnet': '192.0.2.0/24', 'lan_address': '192.0.2.1'},
    'routing': {'mode': 'off', 'default_upstream': 'dpn'},
    'upstreams': {'dpn': {'enabled': True}}, 'provider': {'enabled': True}}))" >/dev/null 2>&1 || true
  fi
  docker rm -f "$WEB" "$PHONE" "$PLAIN" "$PERSON" >/dev/null 2>&1 || true
  docker network rm "$INTERNET" "$PHONES" >/dev/null 2>&1 || true
  sudo rm -rf "$WORK"
}
trap cleanup EXIT

fail() {
  echo "FAIL: $*" >&2
  {
    echo "--- diagnostics"
    echo "# containers"; docker ps -a --format '{{.Names}} {{.Status}}'
    echo "# firewall"; sudo nft list table inet vibedpn
    echo "# server (no keys)"; docker exec vibedpn-wg-server-1 awg show wg0 | grep -v -i key
    echo "# phone"; docker logs --tail 15 "$PHONE" 2>&1
    echo "# wg-server"; docker logs --tail 15 vibedpn-wg-server-1 2>&1
    echo "# access server"; docker logs --tail 20 vibedpn-access-1 2>&1 || true
    echo "# core"; docker logs --tail 25 vibedpn-core-1 2>&1
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
docker image inspect "$CORE_IMAGE" "$WG_IMAGE" "$XRAY_IMAGE_OF_BOX" >/dev/null 2>&1 ||
  fail "build $CORE_IMAGE, $WG_IMAGE and $XRAY_IMAGE_OF_BOX first (docker build -t ... core / images/wg / images/xray)"

# --- the stand ----------------------------------------------------------------------------------
log "stand: the internet and a web server that answers with the exit address"
# nat-unprotected: the real internet has no per-bridge guard on container addresses, and in the
# default nat mode Docker drops what reaches the web server from another interface than its bridge.
docker network create --subnet "$INTERNET_SUBNET" --gateway "$VPS_PUBLIC" \
  -o com.docker.network.bridge.name="$INTERNET_BRIDGE" \
  -o com.docker.network.bridge.gateway_mode_ipv4=nat-unprotected "$INTERNET" >/dev/null
docker network create --subnet "$PHONES_SUBNET" --gateway "$PHONES_GATEWAY" \
  -o com.docker.network.bridge.name="$PHONES_BRIDGE" \
  -o com.docker.network.bridge.gateway_mode_ipv4=nat-unprotected "$PHONES" >/dev/null
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

# --- the box ------------------------------------------------------------------------------------
log "init: role vps, no node, no password, the access server on"
mkdir "$BOX"
cp "$REPO/compose.yaml" "$BOX/"
init_out="$(sudo "$CLI" init --dir "$BOX" --role vps --no-provider --access --endpoint "$VPS_PUBLIC")" ||
  fail "vibedpn init --role vps --no-provider --access failed: $init_out"
sudo sed -i "s/^VIBEDPN_TAG=.*/VIBEDPN_TAG=$TAG/" "$BOX/.env"
grep -q "^COMPOSE_PROFILES=wg-server,access$" "$BOX/.env" ||
  fail "init did not leave exactly wg-server and access: $(grep COMPOSE_PROFILES "$BOX/.env")"
sudo test ! -e "$BOX/secrets/htpasswd" || fail "a bare VPS has a panel password"
sudo test ! -e "$BOX/data/myst-provider" || fail "a bare VPS has the data of a node"
grep -q "^    jc: " "$BOX/config.yaml" || fail "init wrote no AmneziaWG parameters"
if grep -qi "HeaderProtectionKey" "$BOX/config.yaml"; then
  fail "the header protection key is in config.yaml"
fi
if [ "$OFFLINE" = 1 ]; then
  sudo "$CLI" access disable --dir "$BOX" >/dev/null || fail "vibedpn access disable failed"
  echo "offline: the access server is off after init (REALITY needs a real cover site)"
fi

log "up: the tunnel server only"
sudo "$CLI" up --dir "$BOX" >/dev/null 2>&1 || fail "vibedpn up failed"
wait_healthy() {
  i=0
  until [ "$(docker inspect -f '{{.State.Health.Status}}' "$1" 2>/dev/null || true)" = healthy ]; do
    i=$((i + 1))
    [ "$i" -lt "$TIMEOUT" ] || fail "$1 never became healthy"
    sleep 2
  done
}
wait_healthy vibedpn-core-1
wait_healthy vibedpn-wg-server-1
if docker ps -a --format '{{.Names}}' | grep -E 'myst|ui-1|adguard'; then
  fail "a bare VPS runs a node, a panel or AdGuard"
fi

log "firewall: ssh, the tunnel port, the core API in the tunnel — and nothing of a node"
ruleset="$(sudo nft list table inet vibedpn)" || fail "the firewall table of the VPS is not loaded"
printf '%s\n' "$ruleset" | grep -q 'udp dport 51820 accept' || fail "the tunnel port is closed"
if printf '%s\n' "$ruleset" | grep -qE 'myst_udp|4449'; then
  fail "the firewall of a bare VPS opens something of a node"
fi
echo "$ruleset" | grep -E 'dport|policy'

log "AmneziaWG on the server: the parameters of config.yaml, the key in secrets/"
sudo test -f "$BOX/secrets/wg-server/header-protection.key" || fail "core made no header protection key"
[ "$(sudo stat -c '%a' "$BOX/secrets/wg-server/header-protection.key")" = 600 ] ||
  fail "the header protection key is not mode 600"
config_jc="$(sed -n 's/^    jc: //p' "$BOX/config.yaml")"
[ "$(docker exec vibedpn-wg-server-1 awg show wg0 jc)" = "$config_jc" ] ||
  fail "the running server does not carry Jc $config_jc of config.yaml"
server_header_key="$(docker exec vibedpn-wg-server-1 awg show wg0 header-protection-key)"
[ -n "$server_header_key" ] || fail "the running server has no header protection key"

log "peer add: a file for a phone, full tunnel, with the same parameters and key"
sudo "$CLI" peer add phone --out "$WORK/phone.conf" --dir "$BOX" | grep -q "AmneziaWG app" ||
  fail "vibedpn peer add phone failed or does not say where the file goes"
sudo grep -q "^Jc = $config_jc$" "$WORK/phone.conf" || fail "the phone file has no Jc of the server"
sudo grep -q "^HeaderProtectionKey = $server_header_key$" "$WORK/phone.conf" ||
  fail "the phone file has another header protection key than the server"
sudo grep -q "^AllowedIPs = 0.0.0.0/0$" "$WORK/phone.conf" || fail "the phone file is not a full tunnel"
sudo grep -q "^Endpoint = $VPS_PUBLIC:51820$" "$WORK/phone.conf" || fail "the phone file dials another endpoint"
sudo "$CLI" peer add phone2 --dir "$BOX" | grep -E '█|▀|▄' >/dev/null || fail "peer add prints no QR code"
sudo "$CLI" peer rm phone2 --yes --dir "$BOX" >/dev/null || fail "vibedpn peer rm phone2 failed"
sudo "$CLI" peer export phone --out "$WORK/phone-again.conf" --dir "$BOX" >/dev/null ||
  fail "vibedpn peer export phone failed"
sudo cmp "$WORK/phone.conf" "$WORK/phone-again.conf" || fail "peer export does not repeat the file of peer add"

log "a phone with the file: handshake, and the exit is the VPS"
sudo chmod 644 "$WORK/phone.conf"
phone() {
  # $1: container, $2: ip, $3: file
  docker run -d --name "$1" --network "$PHONES" --ip "$2" --cap-add NET_ADMIN \
    --device /dev/net/tun --sysctl net.ipv4.ip_forward=1 --sysctl net.ipv4.conf.all.src_valid_mark=1 \
    -v "$3:/etc/wireguard/wg0.conf:ro" "$WG_IMAGE" client >/dev/null
}
phone "$PHONE" "$PHONE_IP" "$WORK/phone.conf"
i=0
until docker exec "$PHONE" /usr/local/bin/entrypoint.sh health >/dev/null 2>&1; do
  i=$((i + 1))
  [ "$i" -lt "$TIMEOUT" ] || fail "the phone never handshook with the obfuscated server"
  sleep 2
done
seen="$(docker exec "$PHONE" wget -qO- -T 10 "http://$WEB_IP:$WEB_PORT/" 2>/dev/null || true)"
[ "$seen" = "$VPS_PUBLIC" ] || fail "the web server sees '${seen:-nothing}' for the phone, not the VPS $VPS_PUBLIC"
echo "the phone leaves as $seen"
sudo "$CLI" peer list --dir "$BOX" | grep -E '^phone +10\.78\.0\.2 ' | grep -qv never ||
  fail "peer list does not show the handshake of the phone"

log "the keys act on the wire: a phone without them never handshakes"
sudo "$CLI" peer add plain --out "$WORK/plain-full.conf" --dir "$BOX" >/dev/null || fail "vibedpn peer add plain failed"
# the same peer, the obfuscation lines taken out: what a plain WireGuard app would send
sudo chmod 644 "$WORK/plain-full.conf"
grep -vE '^(Jc|Jmin|Jmax|S[1-4]|H[1-4]|HeaderProtectionKey) = ' "$WORK/plain-full.conf" >"$WORK/plain.conf"
phone "$PLAIN" "$PLAIN_IP" "$WORK/plain.conf"
sleep "$MISMATCH_SECONDS"
plain_pub="$(docker exec "$PLAIN" awg show wg0 public-key)"
[ "$(docker exec vibedpn-wg-server-1 awg show wg0 latest-handshakes | awk -v key="$plain_pub" '$1 == key { print $2 }')" = 0 ] ||
  fail "a peer without the obfuscation keys handshook with an obfuscated server"
echo "no handshake without the keys"

log "the header protection key stays out of logs and terminals"
dump_line="$(docker exec vibedpn-wg-server-1 awg show wg0 dump | head -n 1)"
printf '%s' "$dump_line" | grep -qF "$server_header_key" ||
  fail "the first line of the dump does not carry the key: the redaction check proves nothing"
redacted="$(printf '%s' "$dump_line" | sudo "$PY" -c 'import sys; from vibedpn.engine.logs import redact; print(redact(sys.stdin.read()))')"
printf '%s' "$redacted" | grep -qF "$server_header_key" && fail "redact leaves the header protection key"
echo "the dump line is redacted"

if [ "$OFFLINE" = 1 ]; then
  echo "skipped: the person of the access server (VIBEDPN_E2E_OFFLINE=1)"
else
  log "access add: a link, and a VLESS client through REALITY leaves as the VPS"
  wait_healthy vibedpn-access-1
  sudo "$CLI" access add anna --out "$WORK/anna.link" --dir "$BOX" >/dev/null || fail "vibedpn access add anna failed"
  sudo grep -q "@$VPS_PUBLIC:443" "$WORK/anna.link" || fail "the link of anna does not name the endpoint of the VPS"
  mkdir -m 755 "$WORK/person"
  sudo cat "$WORK/anna.link" | "$PY" -c 'import json, sys
from vibedpn.engine.xray import parse_share_link
s = parse_share_link(sys.stdin.read())
print(json.dumps({"log": {"loglevel": "warning"},
 "inbounds": [{"listen": "0.0.0.0", "port": 1080, "protocol": "socks"}],
 "outbounds": [{"protocol": "vless",
  "settings": {"vnext": [{"address": s.host, "port": s.port,
   "users": [{"id": s.uuid, "encryption": "none", "flow": s.flow}]}]},
  "streamSettings": {"network": "raw", "security": s.security, "realitySettings": {
   "serverName": s.sni, "fingerprint": s.fingerprint, "publicKey": s.public_key,
   "shortId": s.short_id}}}]}))' >"$WORK/person/config.json" || fail "cannot build the client of anna from her link"
  docker run -d --name "$PERSON" --network "$PHONES" -p "127.0.0.1:$PERSON_SOCKS:1080" \
    -v "$WORK/person:/usr/local/etc/xray:ro" "$PERSON_IMAGE" >/dev/null
  i=0
  while :; do
    seen="$(curl -s --max-time 6 -x "socks5h://127.0.0.1:$PERSON_SOCKS" "http://$WEB_IP:$WEB_PORT/" 2>/dev/null || true)"
    [ "$seen" = "$VPS_PUBLIC" ] && break
    i=$((i + 1))
    [ "$i" -lt "$TIMEOUT" ] || fail "the VLESS client does not leave as the VPS (the web server sees '${seen:-no connection}')"
    sleep 1
  done
  echo "the person leaves as $seen"
fi

log "doctor: nothing fails"
report="$(sudo "$CLI" doctor --dir "$BOX")" || true
printf '%s\n' "$report"
if printf '%s\n' "$report" | grep -q '^\[FAIL\]'; then
  fail "doctor reports a failure on a healthy bare VPS"
fi

log "bare VPS stand passed"
