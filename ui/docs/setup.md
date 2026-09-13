---
id: setup
tags: setup
description:
  Run the app locally — prerequisites, install, env, database, dev server.
related: postgres, docker
---

# Setup

Get the app running on your machine. Copy-paste the commands top to bottom.

## 1. Prerequisites

- **[Bun](https://bun.sh) ≥ 1.3.14** — runtime, package manager, test runner.
- **Postgres** — a local install (recommended) or Docker. Setup and the SQL to
  create the `vibedpn` / `vibedpn-test` databases: [postgres](./postgres.md). To run
  Postgres in a container instead: [docker](./docker.md).

## 2. Install

```sh
bun install
```

## 3. Environment

```sh
cp env.example .env
```

- `BETTER_AUTH_SECRET` — at least 32 characters: `openssl rand -base64 32`.
- `DATABASE_URL` — the local database from [postgres](./postgres.md).
- `HTPASSWD_FILE` — an htpasswd file with a bcrypt line for `admin`, the same
  format `vibedpn init` writes to `secrets/htpasswd`:
  `printf 'admin:%s
' "$(bun -e 'console.log(await Bun.password.hash(process.argv[1], {algorithm: "bcrypt"}))' 'your-password')" > htpasswd.local`.
- `CORE_API_PORT` — the port of a running core API on 127.0.0.1, if you have one;
  `/api/core/*` answers 502 without it.

Telemetry keys stay empty: the panel sends nothing anywhere unless configured.

## 4. Generate

```sh
bun run generate         # generate the Point0 meta the app imports
```

Run this once now — `bun run seed` (next step) imports the generated Point0 code
and fails without it. From here on it's automatic: `bun dev` and `bun build`
regenerate it on every start.

## 5. Database

```sh
bun run prisma:migrate   # apply migrations to dev + test, regenerate the client
bun run seed             # wipe the dev DB and create the box admin
```

Re-run `bun run prisma:migrate` after any change to
`src/modules/prisma/schema.prisma`.

## 6. Run

```sh
bun dev                  # client + server with HMR
```

- Client: http://localhost:8000
- Server: http://localhost:3000
- Sign in with the password behind `HTPASSWD_FILE`

## 7. Checks and tests

```sh
bun run check            # types + lint
bun run test             # unit + dom + int + e2e
```

Integration and e2e suites use the `vibedpn-test` database and manage it
themselves — keep it clean by letting them run it.
