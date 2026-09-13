# syntax=docker/dockerfile:1
# vibedpn/dnsmasq: DHCP of gateway mode. core renders dnsmasq.conf into ./data/dnsmasq before the
# container starts (compose: depends_on core healthy); the lease file lands in the same directory.
FROM alpine:3.24
RUN apk add --no-cache dnsmasq
ENTRYPOINT ["dnsmasq", "--keep-in-foreground", "--log-facility=-", "--conf-file=/var/lib/vibedpn-dnsmasq/dnsmasq.conf"]
