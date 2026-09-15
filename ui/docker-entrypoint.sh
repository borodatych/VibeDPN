#!/bin/sh
# Refuse to start without the box secrets, then hand the app what it reads from env:
# DATABASE_URL (ui-db on loopback) and BETTER_AUTH_SECRET. The password itself stays in
# HTPASSWD_FILE and is read on every sign-in.
set -eu

SECRETS_DIR=/run/secrets
DB_USER=vibedpn
DB_NAME=vibedpn

for file in "$HTPASSWD_FILE" "$SECRETS_DIR/ui-db-password" "$SECRETS_DIR/ui-auth-secret"; do
    if [ ! -f "$file" ] || [ ! -s "$file" ]; then
        echo "vibedpn-ui: $file is missing or empty; run \`sudo vibedpn init --force\`" >&2
        exit 1
    fi
done
: "${UI_DB_PORT:?UI_DB_PORT is not set}"

db_password="$(cat "$SECRETS_DIR/ui-db-password")"
DATABASE_URL="postgresql://$DB_USER:$db_password@127.0.0.1:$UI_DB_PORT/$DB_NAME?schema=public"
BETTER_AUTH_SECRET="$(cat "$SECRETS_DIR/ui-auth-secret")"
export DATABASE_URL BETTER_AUTH_SECRET

# Seed the shipped languages into the folder the owner sees; a file already there is the owner's and is never replaced.
if [ -n "${LOCALES_DIR:-}" ] && [ -d /app/locales-seed ]; then
    mkdir -p "$LOCALES_DIR"
    for seed in /app/locales-seed/*.json; do
        [ -e "$seed" ] || continue
        target="$LOCALES_DIR/$(basename "$seed")"
        [ -e "$target" ] || cp "$seed" "$target"
    done
fi

exec "$@"
