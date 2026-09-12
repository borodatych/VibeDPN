#!/bin/sh
# Stand-in for the docker CLI in the install test: `docker compose version` succeeds so that
# install.sh skips the Docker Engine step (there is no daemon inside the test container).
case "${1:-} ${2:-}" in
  "compose version")
    echo "v0.0.0-stub"
    exit 0
    ;;
esac
echo "docker-stub: unexpected call: $*" >&2
exit 1
