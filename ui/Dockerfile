# The VibeDPN panel: the start0 app on Bun. Built by CI only — `dist/` needs ~2 GiB of memory,
# more than a Raspberry Pi or a small box has (docs/uiVariants.md).

# ── build stage ── runs on the build platform: `dist/` is the same for every architecture, so it
# is built once, natively, and never under emulation.
FROM --platform=$BUILDPLATFORM oven/bun:1.4.2 AS build
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates openssl && rm -rf /var/lib/apt/lists/*
COPY package.json bun.lock ./
# Lifecycle scripts stay on: the `bun` package's postinstall is required by `point0 build`.
RUN bun install --frozen-lockfile
COPY . .
# full (N100) or lite (Raspberry Pi), inlined into both bundles as a build-time constant (src/lib/variant.ts).
ARG UI_VARIANT=full
ENV UI_VARIANT=$UI_VARIANT
# `prisma generate` uses a throwaway URL (prisma.config.ts): no database at build time.
RUN bunx prisma generate && bun run build:code && find dist/client -type f -name '*.map' -delete

# ── runtime stage ── per architecture: production dependencies (the Prisma CLI for migrations and
# native addons), the built `dist/`, and the Prisma schema with its migrations.
FROM oven/bun:1.4.2 AS runtime
WORKDIR /app
ARG UI_VARIANT=full
ENV UI_VARIANT=$UI_VARIANT \
    NODE_ENV=production \
    HOST_ENV=prod \
    HTPASSWD_FILE=/run/secrets/htpasswd
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates openssl && rm -rf /var/lib/apt/lists/*
COPY --from=build /app/package.json /app/bun.lock ./
RUN bun install --frozen-lockfile --production
COPY --from=build /app/dist ./dist
COPY --from=build /app/src/modules/prisma/schema.prisma ./src/modules/prisma/schema.prisma
COPY --from=build /app/src/modules/prisma/migrations ./src/modules/prisma/migrations
COPY --from=build /app/prisma.config.ts ./prisma.config.ts
COPY docker-entrypoint.sh /usr/local/bin/vibedpn-ui-entrypoint
RUN chmod 0755 /usr/local/bin/vibedpn-ui-entrypoint
ENTRYPOINT ["/usr/local/bin/vibedpn-ui-entrypoint"]
CMD ["sh", "-c", "bunx prisma migrate deploy && exec bun run ./dist/server/index.server.js"]
