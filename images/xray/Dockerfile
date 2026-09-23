# Xray for two jobs, one binary. `run`: the gateway of uplink `xray`, a masking transport (VLESS/
# Reality, Shadowsocks and the rest Xray speaks) for a network where plain WireGuard does not pass.
# `serve`: the access server of the owner's people (decision 30). The binary comes from the official
# image; the shell around it is ours, because that image is distroless and carries no nft.
FROM ghcr.io/xtls/xray-core:26.3.27 AS upstream

FROM debian:trixie-slim
COPY --from=upstream /usr/local/bin/xray /usr/local/bin/xray
# curl: the health check of the server asks its counters through itself. setcap: the server is not
# root and still answers on 443 — the capability lives on the binary. libcap2-bin stays: iproute2
# depends on it, and purging it takes ss away from the health check of the gateway.
RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl iproute2 libcap2-bin nftables \
  && setcap cap_net_bind_service=+ep /usr/local/bin/xray \
  && rm -rf /var/lib/apt/lists/*
# The users the traffic of each job is recognised by. The ids are fixed because core hands them
# their rendered configuration by number (engine/xray.py, engine/access.py) and the router of the
# host steers the server's traffic by its uid (engine/router.py, ACCESS_UID).
RUN groupadd --system --gid 7754 vibedpn-xray \
  && useradd --system --uid 7754 --gid 7754 --no-create-home --shell /usr/sbin/nologin vibedpn-xray \
  && groupadd --system --gid 7755 vibedpn-access \
  && useradd --system --uid 7755 --gid 7755 --no-create-home --shell /usr/sbin/nologin vibedpn-access
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["run"]
