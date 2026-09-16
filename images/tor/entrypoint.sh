#!/bin/sh
# vibedpn/tor entrypoint: `run` (the gateway) or `health` (what the compose healthcheck runs).
#
# The LAN router of the host sends the marked traffic of uplink `tor` to this container's address.
# Tor carries TCP only, so the container does not route at all: TCP arriving from the bridge is
# redirected to the TransPort of tor, DNS to its DNSPort, and everything else is dropped — nothing
# leaves this container except what tor itself sends, which is the kill switch.
#
# The bridges come from core (`upstreams.tor.bridges` → data/tor/bridges); tor itself keeps its
# state in data/tor/state, so a restart does not bootstrap from scratch.
set -eu

CONFIG_DIR=/etc/vibedpn-tor
BRIDGES_FILE="$CONFIG_DIR/bridges"
STATE_DIR=/var/lib/tor
TORRC=/run/vibedpn-tor/torrc
NOTICE_LOG=/run/vibedpn-tor/notices.log
TOR_USER=debian-tor
TRANS_PORT=9040
DNS_PORT=5353
SOCKS_PORT=9050
NFT_TABLE=vibedpn_tor
# The embedded DNS of Docker: the container resolves the fronting domains of the transports here.
DOCKER_DNS=127.0.0.11
# Hosts behind a .onion or an automapped name get addresses from this range (tor-resolve).
VIRTUAL_NETWORK=10.192.0.0/10

log() {
  echo "vibedpn/tor: $*" >&2
}

die() {
  log "$*"
  exit 1
}

# One ClientTransportPlugin per transport the bridge lines name; a bridge line starts with the
# transport, a line of a plain relay (an address) needs none.
transport_plugins() {
  awk '
    { sub(/\r$/, ""); sub(/#.*/, ""); gsub(/^[ \t]+|[ \t]+$/, "") }
    $0 == "" { next }
    $1 == "snowflake" { snowflake = 1 }
    $1 == "obfs4" || $1 == "meek_lite" { obfs4 = 1 }
    $1 == "webtunnel" { unsupported = unsupported " " $1 }
    END {
      if (snowflake) print "ClientTransportPlugin snowflake exec /usr/bin/snowflake-client"
      if (obfs4) print "ClientTransportPlugin obfs4,meek_lite exec /usr/bin/obfs4proxy"
      if (unsupported != "") print "#unsupported" unsupported
    }' "$BRIDGES_FILE"
}

write_torrc() {
  [ -s "$BRIDGES_FILE" ] || die "$BRIDGES_FILE is missing or empty: core writes it from upstreams.tor.bridges"
  plugins="$(transport_plugins)"
  case "$plugins" in
    *"#unsupported"*) die "bridges of a transport this image has no client for:${plugins##*#unsupported}" ;;
  esac
  mkdir -p "$(dirname "$TORRC")"
  {
    echo "DataDirectory $STATE_DIR"
    echo "User $TOR_USER"
    echo "Log notice stdout"
    echo "Log notice file $NOTICE_LOG"
    echo "SocksPort 127.0.0.1:$SOCKS_PORT"
    echo "TransPort 0.0.0.0:$TRANS_PORT"
    echo "DNSPort 0.0.0.0:$DNS_PORT"
    echo "VirtualAddrNetworkIPv4 $VIRTUAL_NETWORK"
    echo "AutomapHostsOnResolve 1"
    echo "UseBridges 1"
    echo "$plugins"
    awk '
      { sub(/\r$/, ""); sub(/#.*/, ""); gsub(/^[ \t]+|[ \t]+$/, "") }
      $0 != "" { print "Bridge " $0 }' "$BRIDGES_FILE"
  } >"$TORRC"
}

# Everything from the bridge goes to tor or nowhere. The traffic of this container itself (the exit
# check of `vibedpn doctor` runs wget here) goes through tor as well, except tor and its transports,
# which run as TOR_USER and are the only ones allowed out.
apply_firewall() {
  nft -f - <<EOF
add table ip $NFT_TABLE
delete table ip $NFT_TABLE
table ip $NFT_TABLE {
  chain prerouting {
    type nat hook prerouting priority dstnat; policy accept;
    fib daddr type local return
    ip protocol tcp redirect to :$TRANS_PORT
    udp dport 53 redirect to :$DNS_PORT
  }
  chain output_nat {
    type nat hook output priority -100; policy accept;
    meta skuid "$TOR_USER" return
    ip daddr 127.0.0.0/8 return
    ip protocol tcp redirect to :$TRANS_PORT
    udp dport 53 redirect to :$DNS_PORT
  }
  chain forward {
    type filter hook forward priority filter; policy drop;
  }
  chain output {
    type filter hook output priority filter; policy drop;
    oifname "lo" accept
    meta skuid "$TOR_USER" accept
    ct state established,related accept
    ip daddr $DOCKER_DNS accept
  }
}
EOF
}

run() {
  write_torrc
  apply_firewall
  mkdir -p "$STATE_DIR"
  chown -R "$TOR_USER:$TOR_USER" "$STATE_DIR" "$(dirname "$NOTICE_LOG")"
  chmod 700 "$STATE_DIR"
  : >"$NOTICE_LOG"
  chown "$TOR_USER:$TOR_USER" "$NOTICE_LOG"
  log "starting tor with $(grep -c '^Bridge ' "$TORRC") bridges"
  exec tor -f "$TORRC"
}

# Healthy once tor has finished bootstrapping in this run; the notice log is written anew at start.
health() {
  [ -f "$NOTICE_LOG" ] || exit 1
  last="$(grep 'Bootstrapped' "$NOTICE_LOG" | tail -n 1)"
  case "$last" in
    *"Bootstrapped 100%"*) exit 0 ;;
    *) exit 1 ;;
  esac
}

case "${1:-run}" in
  run) run ;;
  health) health ;;
  *) die "unknown mode ${1}: run or health" ;;
esac
