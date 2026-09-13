---
id: worker
description:
  Background work on pg-boss — when to reach for a worker, and the naming /
  registration conventions.
tags: rule, setup, worker, pg-boss
---

# Workers

Background jobs run on [pg-boss](https://github.com/timgit/pg-boss) — a
Postgres-backed queue living **in the same process** as the web server (no
Redis, no separate worker node). `startWorkers()` (`worker-index`) registers
every module's workers at boot; pg-boss then polls Postgres and runs jobs off
the request thread, retrying and deduping as configured.

## When to reach for one

Use a worker when work should be **queued or scheduled** — run off the request
thread, retried, deduped, or on a cron. Plain in-request logic doesn't need one;
just call the function.

When a function has a `*Worker` wrapper, prefer `worker.send(...)` over calling
it directly: the retry / dedupe / transaction-scoping / off-request guarantees
are lost when a caller reaches past it. Call the bare function only from inside
the worker handler, from tests, or a one-off script where queueing is overkill.

## Conventions

- Name every worker export with a `Worker` suffix (`syncFooWorker`, not
  `syncFoo`).
- Put a module/feature's workers in its `worker.ts`, exporting
  `start<Module>Workers()` that `.start()`s each one.
- Register every `start<Module>Workers` in `index.ts`'s `startWorkers()`.

Define each worker with `createWorker` (or `createBatchWorker`) — never enqueue
on raw pg-boss directly.
