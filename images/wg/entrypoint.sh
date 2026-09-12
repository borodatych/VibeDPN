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
# The tunnel gets this long to come up before the watchdog starts judging its handshakes.
WATCHDOG_GRACE_SECONDS=60
# A gateway behind NAT needs keepalive to stay reachable; a peer file without it gets this.
KEEPALIVE_SECONDS=25
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

# Every value of a key in the [Interface] section, in order: a key may be repeated (wg-quick
# accumulates Address that way). Keys are case-insensitive, comments start with '#', and a
# trailing CR of a file written on Windows is dropped.
conf_values() {
  awk -v key="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" '
    { line = $0; sub(/\r$/, "", line); sub(/#.*/, "", line); gsub(/^[ \t]+|[ \t]+$/, "", line) }
    line ~ /^\[/ { in_interface = (tolower(line) == "[interface]"); next }
    !in_interface || index(line, "=") == 0 { next }
    {
      eq = index(line, "=")
      name = substr(line, 1, eq - 1); value = substr(line, eq + 1)
      gsub(/^[ \t]+|[ \t]+$/, "", name); gsub(/^[ \t]+|[ \t]+$/, "", value)
      if (tolower(name) == key && value != "") print value
    }' "$CONF"
}

# The last value of a key, the way wg-quick resolves a repeated MTU.
conf_field() {
  conf_values "$1" | tail -n 1
}

# The config without the keys wg-quick invented: wg(8) itself knows only PrivateKey, ListenPort
# and FwMark in [Interface], and `wg setconf` fails on anything else.
#
# A client gets FwMark written in: the kill switch lets WireGuard's own encrypted packets out by
# that mark, so it has to be set before the first handshake leaves, not after `setconf` returns.
strip_conf() {
  awk -v fwmark="$1" '
    { line = $0; sub(/\r$/, "", line); sub(/#.*/, "", line); gsub(/^[ \t]+|[ \t]+$/, "", line) }
    line == "" { next }
    line ~ /^\[/ {
      in_interface = (tolower(line) == "[interface]")
      print line
      if (in_interface && fwmark != "") print "FwMark = " fwmark
      next
    }
    {
      eq = index(line, "=")
      if (in_interface && eq > 0) {
        name = tolower(substr(line, 1, eq - 1)); gsub(/^[ \t]+|[ \t]+$/, "", name)
        if (name ~ /^(address|mtu|dns|table|preup|postup|predown|postdown|saveconfig)$/) next
        if (fwmark != "" && name == "fwmark") next  # ours wins: the kill switch keys on it
      }
      print line
    }' "$CONF"
}

# The config the interface was built from, as a digest. core re-renders wg0.conf at every start
# and replaces it atomically, so a different digest means the running tunnel is out of date.
conf_digest() {
  sha256sum "$CONF" 2>/dev/null | cut -d' ' -f1
}

# Every AllowedIPs entry of every peer, one per line.
allowed_ips() {
  wg show "$IFACE" allowed-ips | awk '{ for (field = 2; field <= NF; field++) print $field }' |
    tr ',' '\n' | sed '/^$/d'
}

route_everything_into_the_tunnel() {
  # AllowedIPs 0.0.0.0/0: a plain default route would send the encrypted packets into the
  # tunnel as well. The mark from the config keeps them out of it; `suppress_prefixlength 0`
  # keeps the specific routes of the main table — the local bridge — while ignoring its default.
  ip route replace default dev "$IFACE" table "$FWMARK"
  ip rule add not fwmark "$FWMARK" table "$FWMARK"
  ip rule add table main suppress_prefixlength 0
}

add_routes() {
  allowed_ips | while read -r cidr; do
    case "$cidr" in
      0.0.0.0/0)
        # In mode server the interface lives in the host network namespace, and its routing
        # belongs to core alone (engine/router.py never touches the default route either).
        [ "$MODE" = client ] ||
          die "AllowedIPs 0.0.0.0/0 in a server config would rewrite the routing of the VPS itself"
        route_everything_into_the_tunnel
        ;;
      *:*) log "ignoring IPv6 AllowedIPs $cidr (the tunnel is IPv4 until the roadmap says otherwise)" ;;
      *) ip route replace "$cidr" dev "$IFACE" ;;
    esac
  done
}

# Without keepalive an idle tunnel stops re-handshaking and the peer forgets the NAT mapping;
# both the health check and the watchdog would then call a working tunnel dead.
ensure_keepalive() {
  wg show "$IFACE" persistent-keepalive | while read -r peer interval; do
    [ "$interval" = off ] || continue
    log "a peer has no PersistentKeepalive; setting ${KEEPALIVE_SECONDS}s"
    wg set "$IFACE" peer "$peer" persistent-keepalive "$KEEPALIVE_SECONDS"
  done
}

setup_interface() {
  [ -r "$CONF" ] || die "$CONF is missing or unreadable; run \`vibedpn init\` on this box"
  CONF_DIGEST="$(conf_digest)"
  # In mode server the interface lives in the host network namespace and outlives a container
  # that was killed rather than stopped; recreating it is what makes a restart work at all.
  # On a VibeDPN box wg0 belongs to VibeDPN — see docs/manuals/installation.md.
  if ip link show "$IFACE" >/dev/null 2>&1; then
    log "$IFACE was left over by an earlier run; recreating it"
    ip link del "$IFACE"
  fi
  ip link add "$IFACE" type wireguard ||
    die "cannot create $IFACE: the host kernel needs the wireguard module (\`vibedpn doctor\`)"
  stripped="$STATE_DIR/$IFACE.conf"
  if [ "$MODE" = client ]; then
    strip_conf "$FWMARK" >"$stripped"
  else
    strip_conf "" >"$stripped"
  fi
  wg setconf "$IFACE" "$stripped" || die "$CONF is not a valid WireGuard configuration"
  rm -f "$stripped"
  addresses="$(conf_values Address | tr ',\n' '  ')"
  [ -n "$addresses" ] || die "$CONF has no Address in its [Interface] section"
  applied=0
  for address in $addresses; do
    case "$address" in
      *:*) log "ignoring IPv6 Address $address (the tunnel is IPv4 for now)" ;;
      *)
        ip address add "$address" dev "$IFACE"
        applied=$((applied + 1))
        ;;
    esac
  done
  [ "$applied" -gt 0 ] || die "$CONF gives $IFACE no IPv4 address"
  mtu="$(conf_field MTU)"
  ip link set mtu "${mtu:-$DEFAULT_MTU}" up dev "$IFACE"
  add_routes
  if [ "$MODE" = client ]; then
    ensure_keepalive
  fi
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
  while ip rule del not fwmark "$FWMARK" table "$FWMARK" 2>/dev/null; do :; done
  while ip rule del table main suppress_prefixlength 0 2>/dev/null; do :; done
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
  started="$(date +%s)"
  while interface_is_up; do
    # A client keeps the tunnel honest: wg resolves Endpoint once, so a VPS that moved to a new
    # address is only fixed by starting over — which is what a non-zero exit gets us.
    if [ "$MODE" = client ] && [ $(($(date +%s) - started)) -gt "$WATCHDOG_GRACE_SECONDS" ]; then
      age="$(handshake_age)"
      [ "$age" -le "$HANDSHAKE_MAX_AGE_SECONDS" ] ||
        die "no handshake for ${age}s; rebuilding the tunnel"
    fi
    # After a reboot Docker restarts containers on its own and ignores depends_on, so this one
    # may have read wg0.conf before core re-rendered it. Starting over picks up the new file.
    [ "$(conf_digest)" = "$CONF_DIGEST" ] || die "$CONF changed; rebuilding the tunnel from it"
    sleep "$WATCH_SECONDS" &
    wait "$!" || true
  done
  die "$IFACE is down"
}

# Seconds since the newest handshake with any peer; when there was none at all, long enough to
# count as dead.
handshake_age() {
  wg show "$IFACE" latest-handshakes |
    awk -v now="$(date +%s)" '
      { if ($2 > newest) newest = $2 }
      # The parentheses matter: bare `print a > b` in awk redirects into a file named b.
      END { print (newest > 0 ? now - newest : now) }'
}

health() {
  [ -f "$MODE_FILE" ] || die "not configured yet"
  interface_is_up || die "$IFACE is down"
  [ "$(cat "$MODE_FILE")" = client ] || exit 0  # a server without peers is healthy
  age="$(handshake_age)"
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
# The kill switch goes in first: nftables matches an interface by name, so the rules are valid
# before wg0 exists and there is no window in which traffic could route around the tunnel.
if [ "$MODE" = client ]; then
  install_kill_switch
fi
setup_interface
printf '%s\n' "$MODE" >"$MODE_FILE"
log "$IFACE is up in mode $MODE"
trap 'teardown' TERM INT
watch_interface
