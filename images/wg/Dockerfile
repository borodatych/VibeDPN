# syntax=docker/dockerfile:1
# vibedpn/wg: WireGuard client or server on the host kernel module, nftables kill switch.
# `wg` only (no wg-quick): routes and firewall are set explicitly by the entrypoint.
FROM alpine:3.24
RUN apk add --no-cache wireguard-tools-wg iproute2 nftables
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["client"]
