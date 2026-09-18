# Gateway of uplink `xray`: a masking transport (VLESS/Reality, Shadowsocks and the rest Xray
# speaks) for a network where plain WireGuard does not pass. The binary comes from the official
# image; the shell around it is ours, because that image is distroless and carries no nft.
FROM ghcr.io/xtls/xray-core:26.3.27 AS upstream

FROM debian:trixie-slim
RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates iproute2 nftables \
  && rm -rf /var/lib/apt/lists/*
# The user the traffic of xray itself is recognised by: the kill switch lets out nobody else.
# The id is fixed because core hands it the rendered configuration by number (engine/xray.py),
# exactly as it hands its data to AdGuard.
RUN groupadd --system --gid 7754 vibedpn-xray \
  && useradd --system --uid 7754 --gid 7754 --no-create-home --shell /usr/sbin/nologin vibedpn-xray
COPY --from=upstream /usr/local/bin/xray /usr/local/bin/xray
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["run"]
