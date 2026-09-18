#!/bin/sh
# vibedpn/xray entrypoint: `run` (the gateway) or `health` (what the compose healthcheck runs).
#
# The LAN router of the host sends the marked traffic of uplink `xray` to this container's address.
# Xray is a proxy, not a tunnel: it terminates the connection here and opens its own to the server,
# so TCP arriving from the bridge is redirected to the dokodemo-door inbound and everything else is
# dropped. Nothing leaves this container except what xray itself sends — that is the kill switch.
#
# The configuration is rendered by core (data/xray/config.json) from the share link of the owner:
# the credentials never travel through this image, and the parsing is unit-tested in Python.
set -eu

CONFIG=/etc/vibedpn-xray/config.json
XRAY_USER=vibedpn-xray
# dokodemo-door of the rendered configuration; core writes the same number.
REDIRECT_PORT=12345
NFT_TABLE=vibedpn_xray
# The embedded DNS of Docker: the container resolves the server name of the outbound here.
DOCKER_DNS=127.0.0.11

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
if [ "${1:-}" = health ]; then
  ss -ltnH "sport = :$REDIRECT_PORT" | grep -q LISTEN || exit 1
  exit 0
fi

[ -r "$CONFIG" ] || die "no configuration at $CONFIG (core renders it from upstreams.xray)"

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

apply_firewall
log "gateway rules loaded (table ip $NFT_TABLE), redirect to :$REDIRECT_PORT"
exec setpriv --reuid "$XRAY_USER" --regid "$XRAY_USER" --init-groups \
  /usr/local/bin/xray run -c "$CONFIG"
