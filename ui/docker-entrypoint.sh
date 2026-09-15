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

# Seed the shipped languages into the folder the owner sees. A file is replaced by the one this image ships only while it
# is still exactly what an earlier seeding put there (its sha256 is kept in .seeded/): a file the owner edited, or one
# the owner put there, is never touched.
if [ -n "${LOCALES_DIR:-}" ] && [ -d /app/locales-seed ]; then
    mkdir -p "$LOCALES_DIR/.seeded"
    for seed in /app/locales-seed/*.json; do
        [ -e "$seed" ] || continue
        name="$(basename "$seed")"
        target="$LOCALES_DIR/$name"
        marker="$LOCALES_DIR/.seeded/$name.sha256"
        seed_sum="$(sha256sum "$seed" | cut -d' ' -f1)"
        if [ -e "$target" ]; then
            current_sum="$(sha256sum "$target" | cut -d' ' -f1)"
            [ -f "$marker" ] && [ "$(cat "$marker")" = "$current_sum" ] || continue
            [ "$current_sum" = "$seed_sum" ] && continue
        fi
        cp "$seed" "$target"
        printf '%s\n' "$seed_sum" >"$marker"
    done
fi

exec "$@"
