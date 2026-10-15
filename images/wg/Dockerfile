# syntax=docker/dockerfile:1
# vibedpn/wg: AmneziaWG (WireGuard that DPI does not recognise by signature) as a userspace tunnel,
# client or server, with an nftables kill switch. A plain WireGuard file works too: AmneziaWG with
# no obfuscation keys speaks the WireGuard protocol (docs/knowledge/wireguard/amnezia.md).
# `awg` only (no awg-quick): routes and firewall are set explicitly by the entrypoint.
#
# Alpine 3.24 has no amneziawg package (checked 2026-10-15), so both parts are built from source at
# the exact commits below. A tag can move; a commit cannot, so the commit is what is fetched.
ARG ALPINE_VERSION=3.24
ARG GO_IMAGE=golang:1.26-alpine3.24
# amneziawg-go v3.1.20260828 (AmneziaWG 3.1: header protection, content padding, random trailers)
ARG AMNEZIAWG_GO_TAG=v3.1.20260828
ARG AMNEZIAWG_GO_COMMIT=b5928efb6ca19f0153958460c3d141f04abc5c2e
# amneziawg-tools v3.1.20260812: the `awg` of the same protocol version (and of the Android app)
ARG AMNEZIAWG_TOOLS_COMMIT=ee0f0a9aa34ff0a0da4b3433b9512781cfe02843
# Where amneziawg-go listens for `awg`; core mounts the same directory to read the server's state.
ARG UAPI_SOCKET_DIR=/var/run/amneziawg

# Go cross-compiles, so this stage runs on the builder's own architecture even for arm64.
FROM --platform=$BUILDPLATFORM ${GO_IMAGE} AS daemon
ARG TARGETOS
ARG TARGETARCH
ARG AMNEZIAWG_GO_TAG
ARG AMNEZIAWG_GO_COMMIT
ADD --keep-git-dir=false https://github.com/amnezia-vpn/amneziawg-go.git#${AMNEZIAWG_GO_COMMIT} /src
WORKDIR /src
# The version constant of the repository is stamped by its Makefile from `git describe`, which an
# export without .git cannot do: write the tag in so the daemon reports what it is.
RUN printf 'package main\n\nconst Version = "%s"\n' "${AMNEZIAWG_GO_TAG}" > version.go
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    GOTOOLCHAIN=local CGO_ENABLED=0 GOOS=${TARGETOS} GOARCH=${TARGETARCH} \
    go build -trimpath -ldflags "-s -w" -o /out/amneziawg-go .

# C is built natively for the target (no cross toolchain to maintain); it is a few files.
FROM alpine:${ALPINE_VERSION} AS tools
ARG AMNEZIAWG_TOOLS_COMMIT
ARG UAPI_SOCKET_DIR
RUN apk add --no-cache build-base linux-headers
ADD --keep-git-dir=false https://github.com/amnezia-vpn/amneziawg-tools.git#${AMNEZIAWG_TOOLS_COMMIT} /src
WORKDIR /src/src
# RUNSTATEDIR is where `awg` looks for the daemon's socket (<dir>/amneziawg/<iface>.sock).
RUN make -j"$(nproc)" RUNSTATEDIR="$(dirname "${UAPI_SOCKET_DIR}")" wg \
    && install -D -m 0755 wg /out/awg

FROM alpine:${ALPINE_VERSION}
RUN apk add --no-cache iproute2 nftables
COPY --from=daemon /out/amneziawg-go /usr/local/bin/amneziawg-go
COPY --from=tools /out/awg /usr/local/bin/awg
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["client"]
