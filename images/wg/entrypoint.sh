#!/bin/sh
# vibedpn/wg entrypoint: `client` (uplink gateway with kill switch) or `server` (VPS wg0).
# Stage 0 ships the image and the mode contract; both modes are implemented in Stage 3.
set -eu

MODE="${1:-client}"

case "$MODE" in
  client|server)
    echo "vibedpn/wg: mode '$MODE' is not implemented yet (roadmap Stage 3)" >&2
    exit 1
    ;;
  *)
    echo "vibedpn/wg: unknown mode '$MODE' (expected: client | server)" >&2
    exit 64
    ;;
esac
