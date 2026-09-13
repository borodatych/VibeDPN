---
id: test
tags: test, setup
description:
  The four test kinds (unit, dom, int, e2e), when to use each, and how to run
  them.
related: setup, structure
---

# Tests

Four kinds, sorted by how much they spin up. Reach for the **lightest** one that
can catch the bug.

### unit — `*.unit.test.ts`

Plain Bun, nothing else. For small isolated logic — a util, a pure function, a
schema.

### dom — `*.dom.test.ts`

A DOM (happy-dom) + React Testing Library, no real browser. For React components
and hooks rendered outside a browser.

### int — `*.int.test.ts`

The backend in-process — engine, Prisma, API endpoints — but **no running
server**. For endpoint and backend behavior without paying to boot a server.

### e2e — `*.e2e.test.ts`

The real server plus a real browser (Playwright). For full flows through a
**running** app.

Each kind loads its own setup via `--preload` (`src/test/setup/<kind>.ts`), and
the file suffix is how Bun's filter picks the suite. All run with
`NODE_ENV=test` against the `myapp-test` database.

## Run them

```sh
bun run test         # everything: unit → dom → int → e2e (build)
bun run test:unit
bun run test:dom
bun run test:int
```

## e2e — three ways to get a server

e2e needs a running app; choose how it starts:

```sh
bun run test:e2e:dev     # start the app in dev mode, no build — fast, the default locally
bun run test:e2e:build   # build first, then run the built server — closest to prod (what `bun run test` uses)
bun run test:e2e:no-run  # don't start anything; connect to a server you're already running
```

For the last one, start the server yourself first, then run the tests in another
shell — no per-run boot, so it's the fastest to iterate on:

```sh
bun run dev:test         # NODE_ENV=test dev server
bun run test:e2e:no-run
```

Under the hood (`src/test/setup/e2e.ts`): `E2E_TESTS_BUILD=true` builds and runs
`dist/`; `E2E_TESTS_NO_RUN=true` skips launching; the default runs `point0 dev`.
The setup frees the ports, boots the app, waits for `/api/health` and the client
to be healthy, then kills the app when the run ends.

## Where things live

- `src/test/setup/*` — the per-kind preload setup.
- `src/test/lib/*` — shared test helpers (e.g. `lib/e2e.ts` for browser flows).
- Tests sit next to the code they cover — a module/feature `test/` directory
  (`src/modules/auth/test/`, `src/features/idea/test/`) or right beside the file
  for a single unit (`src/modules/form/core/values.dom.test.tsx`).

## Naming

The stem names the unit a file covers, then the kind suffix:
`<subject>.<kind>.test.ts`.

- **Module/feature default** — the module itself is the subject:
  `<module>/test/<module>.<kind>.test.ts` holds all the module's tests of that
  kind (`auth/test/auth.int.test.ts`, `idea/test/idea.e2e.test.ts`). One stem
  across kinds — the same subject on different rungs of the pyramid.
- **A single file** — the test sits beside it, named after it
  (`values.dom.test.tsx` covers `values.tsx`).
- **A flow or export** — when a default file outgrows itself, split it by
  subject (`sign-up.e2e.test.ts`, `me.int.test.ts`).

The name `smoke` is reserved for `src/test/smoke.e2e.test.ts` — the one test
that only proves the app boots and renders. Everything else says what it tests.
