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
# Present while the tunnel of a client is down: core probes the gateway with ping, and a gateway
# that is up with a dead peer behind it must look silent, or core would route the LAN into it.
PROBE_TABLE=vibedpn_probe
# `wg set fwmark` marks the encrypted packets WireGuard sends out itself. Both the policy
# routing of a full tunnel and the kill switch key on that mark; wg-quick uses the number as
# the routing table id too, and so do we.
FWMARK=51820
# A gateway: replies to a LAN host must leave through the interface the request came in on.
# The full-tunnel rules below consult only the main table's specific routes, and a LAN behind
# the box is reachable only through the main default route (the bridge gateway, i.e. the box),
# so those replies would fall into the tunnel. Connections from outside the tunnel carry this
# conntrack mark; their replies get it as a packet mark and look up the main table first.
RETURN_MARK=0x1
RETURN_RULE_PRIORITY=100
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

# The [Interface] section alone: what cannot change without rebuilding the interface. Lines are
# read the way strip_conf reads them — no comments, no blank lines — because the first [Peer]
# arrives with a blank line in front of it, and that is not a change of the interface.
interface_digest() {
  awk '
    { line = $0; sub(/\r$/, "", line); sub(/#.*/, "", line); gsub(/^[ \t]+|[ \t]+$/, "", line) }
    line == "" { next }
    line ~ /^\[/ { in_interface = (tolower(line) == "[interface]") }
    in_interface { print line }' "$CONF" 2>/dev/null | sha256sum | cut -d' ' -f1
}

# What `wg setconf` and `wg syncconf` get: the config without wg-quick keys, with FwMark for a
# client.
write_stripped() {
  if [ "$MODE" = client ]; then
    strip_conf "$FWMARK" >"$1"
  else
    strip_conf "" >"$1"
  fi
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
  remove_policy_rules  # a peer sync runs this again; `ip rule add` would stack duplicates
  ip rule add not fwmark "$FWMARK" table "$FWMARK"
  ip rule add table main suppress_prefixlength 0
  ip rule add fwmark "$RETURN_MARK" table main priority "$RETURN_RULE_PRIORITY"
}

remove_policy_rules() {
  while ip rule del fwmark "$RETURN_MARK" table main priority "$RETURN_RULE_PRIORITY" 2>/dev/null; do :; done
  while ip rule del not fwmark "$FWMARK" table "$FWMARK" 2>/dev/null; do :; done
  while ip rule del table main suppress_prefixlength 0 2>/dev/null; do :; done
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
  INTERFACE_DIGEST="$(interface_digest)"
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
  write_stripped "$stripped"
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
  chain prerouting {
    type filter hook prerouting priority mangle; policy accept;
    iifname != { "$IFACE", "lo" } ct state new ct mark set $RETURN_MARK comment "a connection this gateway carries for another host"
    iifname "$IFACE" ct mark $RETURN_MARK meta mark set $RETURN_MARK comment "its replies go back the way it came, not into the tunnel"
  }
  chain forward {
    type filter hook forward priority filter; policy drop;
    tcp flags syn tcp option maxseg size set rt mtu comment "LAN MTU 1500, tunnel less: clamp MSS both ways"
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

# Routes follow AllowedIPs: add what is new, drop what no peer claims any more. The route the
# kernel made for the interface address (proto kernel) is left alone; `ip route` prints a host
# route without its /32, so the names are normalised before comparing.
sync_routes() {
  add_routes
  wanted=" $(allowed_ips | tr '\n' ' ') "
  ip -o route show dev "$IFACE" | awk '$0 !~ / proto kernel / { print $1 }' |
    while read -r route; do
      case "$route" in
        */*) cidr="$route" ;;
        *) cidr="$route/32" ;;
      esac
      case "$wanted" in
        *" $cidr "*) ;;
        *) ip route del "$route" dev "$IFACE" ;;
      esac
    done
}

# core re-renders wg0.conf when a peer is added or removed and when config.yaml changes. Peers
# alone are applied in place: `wg syncconf` changes only what differs and keeps every other
# session running (wg(8)). A changed [Interface] — address, port, key — needs the interface
# rebuilt, so the container starts over.
apply_config_change() {
  new_digest="$(conf_digest)"
  if [ "$(interface_digest)" != "$INTERFACE_DIGEST" ]; then
    die "$CONF changed its [Interface] section; rebuilding the tunnel from it"
  fi
  stripped="$STATE_DIR/$IFACE.conf"
  write_stripped "$stripped"
  wg syncconf "$IFACE" "$stripped" || die "wg syncconf rejected $CONF; rebuilding the tunnel"
  rm -f "$stripped"
  sync_routes
  if [ "$MODE" = client ]; then
    ensure_keepalive
  fi
  CONF_DIGEST="$new_digest"
  log "peers of $IFACE updated from $CONF without a restart"
}

# shellcheck disable=SC2329  # invoked through the TERM/INT trap, which ShellCheck cannot see
teardown() {
  trap - TERM INT
  if [ -f "$MODE_FILE" ] && [ "$(cat "$MODE_FILE")" = client ]; then
    nft delete table "$NFT_FAMILY" "$NFT_TABLE" 2>/dev/null || true
    nft delete table "$NFT_FAMILY" "$PROBE_TABLE" 2>/dev/null || true
  fi
  ip link del "$IFACE" 2>/dev/null || true
  remove_policy_rules
  rm -f "$MODE_FILE"
  log "$IFACE is down"
  exit 0
}

# The probe of core gets an answer only while the tunnel works: a handshake within
# HANDSHAKE_MAX_AGE_SECONDS. Then a VPS that died behind a running container is a silent gateway,
# and core holds its traffic or hands it to a fallback uplink (decision 32).
# The table is changed only when the verdict changes; PROBES keeps the last one.
PROBES=""
close_probes() {
  nft -f - <<NFT
add table $NFT_FAMILY $PROBE_TABLE
delete table $NFT_FAMILY $PROBE_TABLE
table $NFT_FAMILY $PROBE_TABLE {
  chain input {
    type filter hook input priority filter; policy accept;
    iifname != { "$IFACE", "lo" } icmp type echo-request drop comment "the tunnel is down: core finds this gateway silent"
  }
}
NFT
  PROBES=closed
}

gate_probes() {
  age="$(handshake_age)"
  if [ "$age" -le "$HANDSHAKE_MAX_AGE_SECONDS" ]; then
    if [ "$PROBES" != open ]; then
      nft delete table "$NFT_FAMILY" "$PROBE_TABLE" 2>/dev/null || true
      PROBES=open
      log "the peer answers: core may route through this gateway"
    fi
  elif [ "$PROBES" != closed ]; then
    close_probes
    log "no handshake for ${age}s: this gateway tells core it is down"
  fi
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
    if [ "$MODE" = client ]; then
      gate_probes
    fi
    # A client keeps the tunnel honest: wg resolves Endpoint once, so a VPS that moved to a new
    # address is only fixed by starting over — which is what a non-zero exit gets us.
    if [ "$MODE" = client ] && [ $(($(date +%s) - started)) -gt "$WATCHDOG_GRACE_SECONDS" ]; then
      age="$(handshake_age)"
      [ "$age" -le "$HANDSHAKE_MAX_AGE_SECONDS" ] ||
        die "no handshake for ${age}s; rebuilding the tunnel"
    fi
    # After a reboot Docker restarts containers on its own and ignores depends_on, so this one
    # may have read wg0.conf before core re-rendered it; and core rewrites it on peer changes.
    if [ "$(conf_digest)" != "$CONF_DIGEST" ]; then
      apply_config_change
    fi
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
# The probes start closed for the same reason: core must not route into a tunnel before its
# first handshake.
if [ "$MODE" = client ]; then
  install_kill_switch
  close_probes
fi
setup_interface
printf '%s\n' "$MODE" >"$MODE_FILE"
log "$IFACE is up in mode $MODE"
trap 'teardown' TERM INT
watch_interface
