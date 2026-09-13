#!/bin/sh
# vibedpn/myst-consumer entrypoint: gateway rules of uplink dpn, then the official node entrypoint.
#
# eth0 is the container's leg on the gateway network (vibedpn-upstreams). LAN traffic the box steers
# here arrives on eth0 and may leave only through another interface — the tunnel the node brings up
# on connect. Without a tunnel there is no other interface, so nothing leaves: the kill switch holds
# whether or not a session exists. The rules do not depend on the name the node gives its tunnel.
# `health` is what the compose healthcheck runs.
set -eu

UPLINK_IF=eth0
TABLE=vibedpn_dpn
TEQUILAPI_PORT=4050
# The host (core) reaches the gateway network from the address of the bridge vibedpn0.
CORE_ADDRESS="${VIBEDPN_CORE_ADDRESS:-10.77.0.1}"
HEALTH_TIMEOUT_SECONDS=3

if [ "${1:-}" = health ]; then
  exec wget -qO /dev/null -T "$HEALTH_TIMEOUT_SECONDS" "http://127.0.0.1:$TEQUILAPI_PORT/healthcheck"
fi

nft -f - <<RULES
add table inet $TABLE
delete table inet $TABLE
table inet $TABLE {
  chain input {
    type filter hook input priority filter; policy accept;
    tcp dport $TEQUILAPI_PORT iifname "lo" accept comment "TequilAPI from inside the container"
    tcp dport $TEQUILAPI_PORT iifname "$UPLINK_IF" ip saddr $CORE_ADDRESS accept comment "TequilAPI from core"
    tcp dport $TEQUILAPI_PORT drop comment "TequilAPI answers without authentication: nobody else, not the LAN, not the tunnel"
  }
  chain forward {
    type filter hook forward priority filter; policy drop;
    tcp flags syn tcp option maxseg size set rt mtu comment "the tunnel MTU is smaller than the LAN's"
    ct state established,related accept
    iifname "$UPLINK_IF" oifname != "$UPLINK_IF" accept comment "LAN traffic leaves only through the tunnel"
  }
  chain postrouting {
    type nat hook postrouting priority srcnat; policy accept;
    oifname != { "$UPLINK_IF", "lo" } masquerade comment "LAN traffic leaves the tunnel as the consumer"
  }
}
RULES
echo "vibedpn/myst-consumer: gateway rules loaded (table inet $TABLE)" >&2

exec /usr/local/bin/docker-entrypoint.sh "$@"
