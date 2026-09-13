#!/bin/sh
# Runs from the nginx image entrypoint as root, before nginx starts.
#
# nginx workers (user nginx) open auth_basic_user_file on every request, and the secret mounted
# from secrets/ is root-only (600) — a worker would answer 500 to every password. Compose cannot
# change the mode of a file mount (uid/gid/mode are ignored for file secrets), so the password
# file is copied here into a location only root and the nginx group can read. A new password
# from `vibedpn init` arrives with `vibedpn restart`, which restarts this container.
set -eu

SOURCE=/run/secrets/htpasswd
TARGET=/etc/nginx/htpasswd

# A missing, empty or non-file secret must stop the container: /api/ is never served without it.
if [ ! -f "$SOURCE" ] || [ ! -s "$SOURCE" ]; then
  echo "vibedpn-ui: $SOURCE is missing or empty; run \`vibedpn init\` on this box" >&2
  exit 1
fi
install -o root -g nginx -m 0440 "$SOURCE" "$TARGET"
echo "vibedpn-ui: password file installed for /api/" >&2
