# syntax=docker/dockerfile:1
# vibedpn/tor: uplink `tor`, a gateway container that carries the TCP of the LAN into Tor through
# bridges (docs/decisions.md, 27). Debian, not Alpine: snowflake-client and obfs4proxy are packaged
# there (trixie), and a pluggable transport is what reaches Tor from a network that blocks it.
FROM debian:trixie-slim
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        tor obfs4proxy snowflake-client nftables ca-certificates wget \
    && rm -rf /var/lib/apt/lists/*
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["run"]
