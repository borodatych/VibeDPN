#!/bin/sh
# vibedpn/wg entrypoint: `server` (the VPS end of the tunnel) or `client` (uplink gateway with
# a kill switch). A third mode, `health`, is what the compose healthcheck runs.
#
# wg-quick is deliberately not used: it needs bash, writes its own nftables table and hides what
# it does behind PostUp hooks. Here the interface, the addresses, the routes and the firewall are
# explicit, and the process stays in the foreground so Docker owns the lifecycle.
set -eu

IFACE=wg0
CONF=/etc/wireguard/wg0.conf
STATE_DIR=/run/vibedpn-wg
MODE_FILE="$STATE_DIR/mode"
NFT_FAMILY=inet
NFT_TABLE=vibedpn_wg
# `wg set fwmark` marks the encrypted packets WireGuard sends out itself. Both the policy
# routing of a full tunnel and the kill switch key on that mark; wg-quick uses the number as
# the routing table id too, and so do we.
FWMARK=51820
DEFAULT_MTU=1420
WATCH_SECONDS=5
# A peer with PersistentKeepalive re-handshakes about every two minutes, so a silence longer
# than this means the tunnel is down, not idle.
HANDSHAKE_MAX_AGE_SECONDS=180

log() {
  echo "vibedpn/wg: $*" >&2
}

die() {
  log "$*"
  exit 1
}

# One value of a key in the [Interface] section. Keys are case-insensitive, comments start
# with '#' and the value keeps its own separators (Address may list several addresses).
conf_field() {
  awk -v key="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" '
    { line = $0; sub(/#.*/, "", line); gsub(/^[ \t]+|[ \t]+$/, "", line) }
    line ~ /^\[/ { in_interface = (tolower(line) == "[interface]"); next }
    !in_interface || index(line, "=") == 0 { next }
    {
      eq = index(line, "=")
      name = substr(line, 1, eq - 1); value = substr(line, eq + 1)
      gsub(/^[ \t]+|[ \t]+$/, "", name); gsub(/^[ \t]+|[ \t]+$/, "", value)
      if (tolower(name) == key && value != "") { print value; exit }
    }' "$CONF"
}

# The config without the keys wg-quick invented: wg(8) itself knows only PrivateKey, ListenPort
# and FwMark in [Interface], and `wg setconf` fails on anything else.
strip_conf() {
  awk '
    { line = $0; sub(/#.*/, "", line); gsub(/^[ \t]+|[ \t]+$/, "", line) }
    line == "" { next }
    line ~ /^\[/ { in_interface = (tolower(line) == "[interface]"); print line; next }
    {
      eq = index(line, "=")
      if (in_interface && eq > 0) {
        name = tolower(substr(line, 1, eq - 1)); gsub(/^[ \t]+|[ \t]+$/, "", name)
        if (name ~ /^(address|mtu|dns|table|preup|postup|predown|postdown|saveconfig)$/) next
      }
      print line
    }' "$CONF"
}

# Every AllowedIPs entry of every peer, one per line.
allowed_ips() {
  wg show "$IFACE" allowed-ips | awk '{ for (field = 2; field <= NF; field++) print $field }' |
    tr ',' '\n' | sed '/^$/d'
}

route_everything_into_the_tunnel() {
  # AllowedIPs 0.0.0.0/0: a plain default route would send the encrypted packets into the
  # tunnel as well. The mark keeps them out of it; `suppress_prefixlength 0` keeps specific
  # routes of the main table (the local bridge) while ignoring its default route.
  wg set "$IFACE" fwmark "$FWMARK"
  ip route replace default dev "$IFACE" table "$FWMARK"
  ip rule add not fwmark "$FWMARK" table "$FWMARK"
  ip rule add table main suppress_prefixlength 0
}

add_routes() {
  allowed_ips | while read -r cidr; do
    case "$cidr" in
      0.0.0.0/0) route_everything_into_the_tunnel ;;
      *:*) log "ignoring IPv6 AllowedIPs $cidr (the tunnel is IPv4 until the roadmap says otherwise)" ;;
      *) ip route replace "$cidr" dev "$IFACE" ;;
    esac
  done
}

setup_interface() {
  [ -r "$CONF" ] || die "$CONF is missing or unreadable; run \`vibedpn init\` on this box"
  ip link add "$IFACE" type wireguard ||
    die "cannot create $IFACE: the host kernel needs the wireguard module (\`vibedpn doctor\`)"
  stripped="$STATE_DIR/$IFACE.conf"
  strip_conf >"$stripped"
  wg setconf "$IFACE" "$stripped" || die "$CONF is not a valid WireGuard configuration"
  rm -f "$stripped"
  addresses="$(conf_field Address)"
  [ -n "$addresses" ] || die "$CONF has no Address in its [Interface] section"
  for address in $(printf '%s' "$addresses" | tr ',' ' '); do
    case "$address" in
      *:*) log "ignoring IPv6 Address $address" ;;
      *) ip address add "$address" dev "$IFACE" ;;
    esac
  done
  mtu="$(conf_field MTU)"
  ip link set mtu "${mtu:-$DEFAULT_MTU}" up dev "$IFACE"
  add_routes
}

# The kill switch of the client gateway. It lives in the container's own network namespace —
# the host firewall belongs to core (engine/router.py) and is never touched from here.
install_kill_switch() {
  nft -f - <<NFT
add table $NFT_FAMILY $NFT_TABLE
delete table $NFT_FAMILY $NFT_TABLE
table $NFT_FAMILY $NFT_TABLE {
  chain output {
    type filter hook output priority filter; policy drop;
    oifname "lo" accept
    oifname "$IFACE" accept comment "into the tunnel"
    meta mark $FWMARK accept comment "the tunnel itself: encrypted packets to the peer"
    fib daddr type local accept
    ct state established,related accept
  }
  chain forward {
    type filter hook forward priority filter; policy drop;
    oifname "$IFACE" accept comment "LAN into the tunnel and nowhere else"
    iifname "$IFACE" ct state established,related accept
  }
  chain postrouting {
    type nat hook postrouting priority srcnat; policy accept;
    oifname "$IFACE" masquerade comment "LAN addresses leave as the tunnel address"
  }
}
NFT
}

# shellcheck disable=SC2329  # invoked through the TERM/INT trap, which ShellCheck cannot see
teardown() {
  trap - TERM INT
  if [ -f "$MODE_FILE" ] && [ "$(cat "$MODE_FILE")" = client ]; then
    nft delete table "$NFT_FAMILY" "$NFT_TABLE" 2>/dev/null || true
  fi
  ip link del "$IFACE" 2>/dev/null || true
  rm -f "$MODE_FILE"
  log "$IFACE is down"
  exit 0
}

# `ip link show up dev` prints the interface only while it is administratively up, and nothing
# at all once it is gone — one check for both ways a tunnel dies.
interface_is_up() {
  [ -n "$(ip -o link show up dev "$IFACE" 2>/dev/null)" ]
}

# Nothing daemonizes: WireGuard lives in the kernel. The container stays in the foreground while
# the interface is up and exits non-zero otherwise, so `restart: unless-stopped` sets the tunnel
# up again from scratch — a downed interface has lost its routes and cannot just be raised.
watch_interface() {
  while interface_is_up; do
    sleep "$WATCH_SECONDS" &
    wait "$!" || true
  done
  die "$IFACE is down"
}

health() {
  [ -f "$MODE_FILE" ] || die "not configured yet"
  interface_is_up || die "$IFACE is down"
  [ "$(cat "$MODE_FILE")" = client ] || exit 0  # a server without peers is healthy
  latest="$(wg show "$IFACE" latest-handshakes |
    awk '{ if ($2 > newest) newest = $2 } END { print newest + 0 }')"
  [ "$latest" -gt 0 ] || die "no handshake with the server yet"
  age=$(($(date +%s) - latest))
  [ "$age" -le "$HANDSHAKE_MAX_AGE_SECONDS" ] ||
    die "the last handshake was ${age}s ago; the tunnel is down"
}

MODE="${1:-client}"
case "$MODE" in
  health)
    health
    exit 0
    ;;
  server | client) ;;
  *)
    log "unknown mode '$MODE' (expected: server | client | health)"
    exit 64
    ;;
esac

umask 077
mkdir -p "$STATE_DIR"
setup_interface
if [ "$MODE" = client ]; then
  install_kill_switch
fi
printf '%s\n' "$MODE" >"$MODE_FILE"
log "$IFACE is up in mode $MODE"
trap 'teardown' TERM INT
watch_interface
