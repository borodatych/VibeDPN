---
id: postgres
tags: db, postgres, setup
description: How we run Postgres locally for this project
related: docker
---

# Postgres

We use a locally installed Postgres rather than a Docker container (for the
compose alternative, see [docker](./docker.md)).

A native install lets you switch between projects instantly without keeping the
Docker daemon running, juggling compose files, or paying the container's startup
time on every machine reboot. Multiple projects share the same server on port
`5432`; each project gets its own user and database.

Recommended installers:

- **macOS** — [Postgres.app](https://postgresapp.com) or
  `brew install postgresql@17`
- **Linux** — your distro's package manager (`apt install postgresql`,
  `pacman -S postgresql`, ...)
- **Windows** — the official
  [EDB installer](https://www.postgresql.org/download/windows/)

## Create the project user and databases

Every project on the machine has two databases: one for development, one for the
integration/e2e test suite. Tests run with `NODE_ENV=test` which selects the
`-test` URL automatically.

Open `psql` and run:

```sql
-- dev
create user "myapp" with encrypted password 'myapp';
alter user "myapp" createdb;
create database "myapp" owner "myapp";
grant all privileges on database "myapp" to "myapp";

-- test
create user "myapp-test" with encrypted password 'myapp-test';
alter user "myapp-test" createdb;
create database "myapp-test" owner "myapp-test";
grant all privileges on database "myapp-test" to "myapp-test";
```

The dev URL is in `env.example`:

```
DATABASE_URL=postgresql://myapp:myapp@localhost:5432/myapp?schema=public
```

For `NODE_ENV=test`, append `-test` to the database name in your `.env.test` (or
however your test env is loaded).

After this, run `bun run prisma:migrate` to create the schema on both databases.

## Wipes and resets

Use `bun run seed` to clean the dev database and reload fixtures — it refuses to
run unless you're on `localhost` with `HOST_ENV=local` (see
[cleanDb](../src/modules/seed/utils.ts) and
[throwIfNotSafeToDestroyDb](../src/modules/seed/utils.ts)). The seed wipes both
the `public` and `pgboss` schemas so background jobs don't fire against fresh
data.
