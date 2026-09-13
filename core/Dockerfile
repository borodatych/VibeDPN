# syntax=docker/dockerfile:1
# Core image: Python 3.12 on Debian 13 (trixie) slim, dependencies from uv.lock only.
FROM python:3.12-slim-trixie AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.13 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project
COPY vibedpn ./vibedpn
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

FROM python:3.12-slim-trixie
# nftables: core programs the host firewall (network_mode: host + NET_ADMIN).
# iptables: core opens Docker's FORWARD drop for the tunnel in DOCKER-USER (both backends).
# wireguard-tools: core reads the live state of the VPS server wg0 (`wg show wg0 dump`) for
# `vibedpn peer list`; it shares the host network namespace with wg-server.
RUN apt-get update \
    && apt-get install -y --no-install-recommends iptables nftables wireguard-tools \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app /app
# Mount points of compose.yaml: config (ro), secrets, state.
RUN mkdir -p /etc/vibedpn/secrets /var/lib/vibedpn
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
WORKDIR /app
CMD ["vibedpn-core"]
