# syntax=docker/dockerfile:1
# Core image: Python 3.12 on Debian 13 (trixie) slim, dependencies from uv.lock only.

# `awg`, built from the same amneziawg-tools commit as in images/wg/Dockerfile (a test compares
# the two). It speaks to the socket of the daemon in wg-server, so the versions must be one.
FROM python:3.12-slim-trixie AS awg
ARG AMNEZIAWG_TOOLS_COMMIT=ee0f0a9aa34ff0a0da4b3433b9512781cfe02843
# Where `awg` looks for the daemon's socket: <dir>/amneziawg/<iface>.sock (compose.yaml mounts it).
ARG RUNSTATEDIR=/var/run
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
ADD --keep-git-dir=false https://github.com/amnezia-vpn/amneziawg-tools.git#${AMNEZIAWG_TOOLS_COMMIT} /src
WORKDIR /src/src
RUN make -j"$(nproc)" RUNSTATEDIR="${RUNSTATEDIR}" wg \
    && install -D -m 0755 wg /out/awg

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
# awg: core reads the live state of the VPS server wg0 (`awg show wg0 dump`) for `vibedpn peer list`
# through the socket of the daemon in wg-server (compose.yaml mounts its directory here).
RUN apt-get update \
    && apt-get install -y --no-install-recommends iproute2 iptables nftables \
    && rm -rf /var/lib/apt/lists/*
COPY --from=awg /out/awg /usr/local/bin/awg
COPY --from=builder /app /app
# Mount points of compose.yaml: config (ro), secrets, state.
RUN mkdir -p /etc/vibedpn/secrets /var/lib/vibedpn
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
WORKDIR /app
CMD ["vibedpn-core"]
