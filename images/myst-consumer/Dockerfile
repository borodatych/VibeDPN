# syntax=docker/dockerfile:1
# vibedpn/myst-consumer: the Mysterium consumer as the gateway of uplink dpn.
# The node's own kill switch (MYST_CONSUMER_KILL_SWITCH) lives in OUTPUT and guards only traffic of
# the container itself; LAN traffic routed through it is FORWARD, and without these rules it would
# leave through eth0 around the tunnel. The entrypoint adds the gateway rules, then runs the node.
ARG MYST_TAG=1.39.5-alpine
FROM mysteriumnetwork/myst:${MYST_TAG}
RUN apk add --no-cache nftables
COPY entrypoint.sh /usr/local/bin/vibedpn-dpn-entrypoint
ENTRYPOINT ["/usr/local/bin/vibedpn-dpn-entrypoint"]
CMD ["--firewall.killSwitch.always", "--ui.enable=false", "--tequilapi.address=0.0.0.0", "daemon"]
