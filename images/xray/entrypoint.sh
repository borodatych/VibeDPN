#!/bin/sh
# vibedpn/xray entrypoint, four modes:
#   run           the gateway of uplink `xray`
#   health        what the compose healthcheck of the gateway runs
#   serve         the access server of the owner's people (decision 30)
#   serve-health  what the compose healthcheck of the access server runs
#
# The gateway. The LAN router of the host sends the marked traffic of uplink `xray` to this
# container's address. Xray is a proxy, not a tunnel: it terminates the connection here and opens
# its own to the server, so TCP arriving from the bridge is redirected to the dokodemo-door inbound
# and everything else is dropped. Nothing leaves this container except what xray itself sends —
# that is the kill switch. The configuration is rendered by core (data/xray/config.json) from the
# share link of the owner: the credentials never travel through this image, and the parsing is
# unit-tested in Python.
#
# The access server runs as its own uid (compose.yaml) with nothing but its data directory. core
# renders the whole configuration there, the table of people and a template for one person
# (engine/access.py); this script starts xray and applies changes of the table through the API of
# Xray, so adding or removing a person drops nobody else's connection.
set -eu

CONFIG=/etc/vibedpn-xray/config.json
XRAY_USER=vibedpn-xray
# dokodemo-door of the rendered configuration; core writes the same number.
REDIRECT_PORT=12345
NFT_TABLE=vibedpn_xray
# The embedded DNS of Docker: the container resolves the server name of the outbound here.
DOCKER_DNS=127.0.0.11

# The access server; the names and numbers are the ones core renders with (engine/access.py).
ACCESS_DIR=/etc/vibedpn-access
ACCESS_API=127.0.0.1:4481
ACCESS_HEALTH_PORT=4483
ACCESS_TAG=people
# How often the table of people is compared with what the running server has.
WATCH_SECONDS=5
TAB=$(printf '\t')
# comm compares byte by byte, the way core sorts the table
export LC_ALL=C

log() {
  echo "vibedpn/xray: $*" >&2
}

die() {
  log "$*"
  exit 1
}

# A gateway is healthy when the port the LAN traffic is redirected to is open: xray opens that
# inbound only after it has read and accepted its configuration. Whether the server on the other
# side answers is a different question, and `vibedpn doctor --network` is the one that asks it.
gateway_health() {
  ss -ltnH "sport = :$REDIRECT_PORT" | grep -q LISTEN
}

apply_firewall() {
  nft -f - <<RULES
add table ip $NFT_TABLE
delete table ip $NFT_TABLE
table ip $NFT_TABLE {
  chain prerouting {
    type nat hook prerouting priority dstnat; policy accept;
    fib daddr type local return
    ip protocol tcp redirect to :$REDIRECT_PORT
  }
  chain forward {
    type filter hook forward priority filter; policy drop;
  }
  chain output {
    type filter hook output priority filter; policy drop;
    oifname "lo" accept
    meta skuid "$XRAY_USER" accept comment "the proxy itself reaches its server; nobody else does"
    ct state established,related accept
    ip daddr $DOCKER_DNS accept comment "the name of the server is resolved by the Docker resolver"
  }
}
RULES
}

gateway() {
  [ -r "$CONFIG" ] || die "no configuration at $CONFIG (core renders it from upstreams.xray)"
  apply_firewall
  log "gateway rules loaded (table ip $NFT_TABLE), redirect to :$REDIRECT_PORT"
  exec setpriv --reuid "$XRAY_USER" --regid "$XRAY_USER" --init-groups \
    /usr/local/bin/xray run -c "$CONFIG"
}

# `xray api` exits 0 whether it changed anything or not: what happened is only in its words.
add_person() {
  email=$1
  id=$2
  request=$(mktemp)
  sed -e "s/@ID@/$id/" -e "s/@EMAIL@/$email/" "$ACCESS_DIR/person.json" >"$request"
  # a person already there (the table and the server met halfway at start) is replaced, not doubled
  xray api rmu --server="$ACCESS_API" -tag="$ACCESS_TAG" "$email" >/dev/null 2>&1 || true
  answer=$(xray api adu --server="$ACCESS_API" "$request" 2>&1 || true)
  rm -f "$request"
  case "$answer" in
    *"Added 1 user"*) log "person $email added" ;;
    *)
      log "cannot add person $email: $answer"
      return 1
      ;;
  esac
}

remove_person() {
  answer=$(xray api rmu --server="$ACCESS_API" -tag="$ACCESS_TAG" "$1" 2>&1 || true)
  case "$answer" in
    *"Removed 1 user"*) log "person $1 removed" ;;
    # already gone is what we wanted
    *) log "person $1 was not on the server: $answer" ;;
  esac
}

# Bring the running server to the table core wrote: removals first, then additions. A changed id is
# both. A table that cannot be read right now is being replaced by core: the next round takes it.
sync_people() {
  applied=$1
  snapshot=$(mktemp)
  if ! cp "$ACCESS_DIR/people.tsv" "$snapshot" 2>/dev/null; then
    rm -f "$snapshot"
    return 0
  fi
  if cmp -s "$snapshot" "$applied"; then
    rm -f "$snapshot"
    return 0
  fi
  comm -23 "$applied" "$snapshot" | cut -f1 | while read -r email; do
    remove_person "$email"
  done
  if ! comm -13 "$applied" "$snapshot" | {
    failed=0
    while IFS="$TAB" read -r email id; do
      add_person "$email" "$id" || failed=1
    done
    exit "$failed"
  }; then
    rm -f "$snapshot"
    return 1
  fi
  mv "$snapshot" "$applied"
}

serve() {
  [ -r "$ACCESS_DIR/config.json" ] ||
    die "no configuration at $ACCESS_DIR/config.json (core renders it when access.enabled is true)"
  applied=$(mktemp)
  cp "$ACCESS_DIR/people.tsv" "$applied" || die "cannot read $ACCESS_DIR/people.tsv"
  /usr/local/bin/xray run -c "$ACCESS_DIR/config.json" &
  xray_pid=$!
  stopping=0
  trap 'stopping=1; kill "$xray_pid" 2>/dev/null || true' TERM INT
  log "access server started, people in its table: $(wc -l <"$applied")"
  while kill -0 "$xray_pid" 2>/dev/null; do
    sleep "$WATCH_SECONDS"
    [ "$stopping" = 0 ] || break
    if ! sync_people "$applied"; then
      # A restart starts from the whole configuration core rendered, which lists everyone.
      log "the server and its table of people disagree; restarting from the configuration"
      kill "$xray_pid" 2>/dev/null || true
      exit 1
    fi
  done
  status=0
  wait "$xray_pid" || status=$?
  [ "$stopping" = 1 ] || die "xray exited with status $status"
}

# Healthy is a real connection through REALITY as the service user, out to the counters of the
# server on loopback: a cover site that does not lend its handshake fails here, before any phone.
serve_health() {
  [ -r "$ACCESS_DIR/health.json" ] || exit 1
  /usr/local/bin/xray run -c "$ACCESS_DIR/health.json" >/dev/null 2>&1 &
  client=$!
  tries=0
  until ss -ltnH "sport = :$ACCESS_HEALTH_PORT" | grep -q LISTEN; do
    tries=$((tries + 1))
    if [ "$tries" -gt 50 ]; then
      kill "$client" 2>/dev/null || true
      exit 1
    fi
    sleep 0.1
  done
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 \
    "http://127.0.0.1:$ACCESS_HEALTH_PORT/debug/vars" || true)
  kill "$client" 2>/dev/null || true
  [ "$code" = 200 ]
}

case "${1:-run}" in
  run) gateway ;;
  health) gateway_health ;;
  serve) serve ;;
  serve-health) serve_health ;;
  *) die "unknown mode ${1}: run, health, serve or serve-health" ;;
esac
