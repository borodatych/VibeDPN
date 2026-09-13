# Boilerplate

A SaaS boilerplate built on **Point0**, Prisma, better-auth, and Tailwind, with
auth, an admin panel, forms, and CRUD already wired. Designed for `bun`
end-to-end (runtime, scripts, tests).

> **Running it the first time? → [docs/setup.md](docs/setup.md).**
> Prerequisites, install, env, database, dev server — copy-paste top to bottom.
> Later, pulling boilerplate updates → [docs/updating.md](docs/updating.md).

## What's inside

- **Point0** — the app framework: pages, layouts, queries, mutations, actions.
- **Prisma** + Postgres — schema, migrations, typed client.
- **better-auth** — email/password and OAuth, sessions, admin.
- **Tailwind** + shadcn-style UI primitives.
- Optional integrations that self-disable without keys: email, product
  analytics, error tracking, and more — see the comments in `env.example`.

## Code layout

See [docs/structure.md](docs/structure.md) for the full layout and naming rules.
Quick map:

- `src/modules/*` — reusable machinery (auth, prisma, email, env, ...)
- `src/features/*` — product features that compose modules (admin, user, ...)
- `src/lib/*` — small named building blocks (root, error, logger, navigation,
  ...)
- `src/components/{ui,blocks,other,hooks}` — UI primitives, composed blocks,
  shared hooks
- `src/pages`, `src/layouts` — top-level routes that don't belong to a feature
- `docs/*` — project-wide conventions. Per-symbol details live in JSDoc next to
  the code

## Where to look next

- [docs/setup.md](docs/setup.md) — run it locally
- [docs/updating.md](docs/updating.md) — pull boilerplate updates
  (`bunx 1gr14@latest update`)
- [docs/structure.md](docs/structure.md) — directory layout and file-naming
  rules
- [docs/docs.md](docs/docs.md) — how we write docs (frontmatter, JSDoc keys,
  `@related`)
- [docs/entity-payloads.md](docs/entity-payloads.md) — the `xxxSelect` +
  `normalize...Payload` convention
- [docs/postgres.md](docs/postgres.md) — local Postgres setup
- [src/modules/form/docs/form.md](src/modules/form/docs/form.md) — form layer
  over react-hook-form
- [src/modules/prisma/README.md](src/modules/prisma/README.md) — Prisma +
  migrations
- [AGENTS.md](AGENTS.md) — operating manual for coding agents
