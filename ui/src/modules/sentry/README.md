---
id: sentry
description:
  How Sentry is wired (one module, env.side, a logger sink), how to lay out
  Sentry projects per app, and the rule that expected errors never go to Sentry.
tags: rule, setup, sentry
---

# Error tracking with Sentry

Errors are sent to [Sentry](https://sentry.io). One module — `@/modules/sentry`
— inits the right SDK per side and exposes `sentryCaptureError`. Capture is
automatic: a LogTape sink forwards every `logger.error` / `logger.fatal` to
Sentry, so the existing error funnels (`root.on('error')`, the client
`ErrorBoundary`) are already covered.

## How to organise projects in Sentry

A Sentry **organization** holds **teams**, teams own **projects**, and each
project has its own **DSN** and event stream. Recommended layout when one
account hosts several apps that each have a backend and a frontend:

- **One organization** for the whole account (billing/quota live here).
- **One team per app/product** — `<app>` — so access and ownership are scoped
  per app.
- **Two projects per app**, one per runtime: `<app>-web` (platform
  `javascript-react`) and `<app>-server` (platform `node`/Bun). Keep them
  separate: different SDKs, different sourcemaps, different alerting. Front and
  back are linked by a shared **release** and, once tracing is on, by
  `tracePropagationTargets` (distributed tracing).
- **Stages are environments, not projects.** `local` / `dev` / `prod` are the
  Sentry `environment` on events (we reuse `HOST_ENV`), so one project per
  runtime covers every stage — filter by environment in the UI.

Setup once: create the team and the two projects in your Sentry org, then wire
their public DSNs into `.env` (`SENTRY_DSN_CLIENT` / `SENTRY_DSN_SERVER`) and
the build-time upload config (`SENTRY_ORG`, `SENTRY_PROJECT_CLIENT`,
`SENTRY_PROJECT_SERVER`).

## How it works in code

`@/modules/sentry` mirrors `@/modules/env` — `client.ts` / `server.ts` /
`shared.ts`:

- **`client.ts`** exports `initSentryClient()` (inits `@sentry/react`);
  **`server.ts`** exports `initSentryServer()` (inits `@sentry/bun`, and
  registers a graceful-shutdown flush so buffered events survive a deploy /
  scale-down). Each is gated by its DSN — no DSN, or local, means Sentry is off
  — and is called by its side's entry point; importing the module has no side
  effect.
- **`shared.ts`** picks the current side with
  `env.side.define({ client: sentryClientApi, server: sentryServerApi })` and
  exposes the reusable helpers: `sentryCaptureError`, `sentryCaptureMessage`,
  `sentrySetUser`, `sentryGetSink`.

The single-file split is safe because the **Point0 compiler** replaces
`env.side.define({ client, server })` with just the current side's branch and
then prunes the now-unused import. So the client bundle never contains
`@sentry/bun` and the server bundle never contains `@sentry/react` — verify with
`grep @sentry/bun dist/client` after a production build (it should be empty).

No index / re-exports: import each helper from the file that declares it. **Init
is explicit and side-specific**: `index.client.tsx` calls `initSentryClient()`
and `index.server.ts` calls `initSentryServer()`, right after the env is
validated, so Sentry is ready before the app boots — the entry points are
already per-side, so there is no shared init. `logger.ts` imports the sink (from
`shared.ts`), which stays a no-op until init has run (`enabled` is false until
then).

To report something by hand, use `sentryCaptureError` (it applies the same
`expected` filter as the sink):

```ts
import { sentryCaptureError } from '@/modules/sentry/shared'

sentryCaptureError(error, { orderId }) // ctx is attached as Sentry `extra`
```

## Rule: expected errors are not sent to Sentry

An error marked **expected** (via the `expected` plugin on
[AppError](../../lib/error.ts)) is a user-facing outcome — a wrong password, a
declined action — not a bug. These belong in the logs, where they can still be
analysed, but they must **not** reach Sentry, or they drown the real bugs.

`sentryCaptureError` and the logger sink both drop `AppError.isExpected(error)`
(it normalizes any input). So the way to keep an error out of Sentry is to mark
it expected:

```ts
throw new AppError('Invalid password', { expected: true })
```

Errors that resolve to expected through their cause chain are dropped too.

## User context

The current user is attached to events on each side, so an issue shows who hit
it:

- **Client** — [`SentryTrackAuth`](./track-auth.tsx) (mounted once in
  `app.client.tsx`) subscribes to the cached `getMeQuery` data with
  `enabled: false` (it never triggers a fetch) and on sign-in / sign-out calls
  `sentrySetUser`. Each analytics tool ships its own self-contained tracker
  (Mixpanel's `MixpanelTrackAuth`), so they subscribe independently with no
  shared wiring.
- **Server** — `sentryServerApi.captureException` reads `request.cache.me` (set
  by `getMe`) via the request context and attaches the user **per event**, so
  concurrent requests never mislabel each other. No global `setUser`, no per-
  request scope assumptions.

The user `id`, `email`, and `username` (the user's name) are attached, so an
issue shows exactly who hit it. This deliberately diverges from the logger,
which stays PII-redacted: Sentry — like Mixpanel — is a trusted store where
recognising the user is the whole point, while logs stream to stdout and leak
into traces, so they don't carry it.

## Environment variables

Runtime (validated in `@/modules/env`). DSNs are **required outside local**
(`HOST_ENV != local`) so prod/dev never ships without Sentry. Sentry is also
**hard-disabled in local** (`HOST_ENV === 'local'`) regardless of the DSN, so a
local checkout never reports to the real project — to test it locally, flip the
`enabled` gate in `client.ts` / `server.ts`. The variables:

- `SENTRY_DSN_SERVER` — server project DSN (server env).
- `SENTRY_DSN_CLIENT` — browser project DSN (client env; injected into the page
  at runtime, public by design).
- `SOURCE_VERSION` — deployed source-code version (usually the git commit). On
  Railway it's resolved at runtime from the injected `RAILWAY_GIT_COMMIT_SHA`
  (see `index.server.ts`); set it explicitly to override. General purpose (app
  display, cache-busting, ...); reused as the Sentry `release`. `HOST_ENV` is
  reused as the Sentry `environment`.

Build-time only (read straight from `process.env` by the sourcemap script, not
validated):

- `SENTRY_AUTH_TOKEN` — enables the upload; without it the step self-skips.
- `SENTRY_ORG`, `SENTRY_PROJECT_SERVER`, `SENTRY_PROJECT_CLIENT`.

## Provisioning & analysis (org auth token)

`SENTRY_API_KEY_ROOT` is an **org-level Sentry auth token**. The app never reads
it: it lives in `env.agents.example` (→ `.env.agents`, gitignored), not
`env.example`, so it stays out of `.env` and the deployed env. It's for a human
or a coding agent to provision Sentry and inspect it.

Create one as a **User Auth Token** (Settings → Account → Auth Tokens) or an
**Internal Integration** (Settings → Developer Settings) with scopes
`project:admin`, `org:read`, `event:read`, `project:releases`. Put it in
`.env.agents`; send it as `Authorization: Bearer ...`.

With it the agent can set Sentry up end to end and then inspect it:

1. Create the two projects (server + web) and read their DSNs to fill
   `SENTRY_DSN_SERVER` / `SENTRY_DSN_CLIENT` (runtime) and the
   `SENTRY_PROJECT_SERVER` / `SENTRY_PROJECT_CLIENT` slugs (build).
2. Mint the narrow build-time `SENTRY_AUTH_TOKEN` (scope `project:releases`) the
   sourcemap upload uses.
3. **Analyze** — query issues/events to debug prod, e.g.
   `GET /api/0/projects/<org>/<project>/issues/?query=is:unresolved`.

## Sourcemaps and releases

Stack traces are only readable with sourcemaps. `bun run build` runs
`sentry:sourcemaps` (`src/modules/sentry/sourcemaps.ts`) after the code build:
it `inject`s Debug IDs into `dist/server` and `dist/client` and uploads the maps
via `@sentry/cli`. This is **bundler-agnostic** — it works whether the client
was built by Bun or Vite, because Point0 emits external `.map` files for both,
and Debug IDs match maps to events regardless of release. The step
**self-skips** when `SENTRY_AUTH_TOKEN` is unset, so local builds stay green. It
only injects + uploads (no deletion); the served client `.map`s are stripped
from `dist/client` in a final Dockerfile step, so they're never published even
when the upload was skipped.

If you switch the client to Vite (uncomment `viteConfig` in `src/engine.ts`),
you may instead use `@sentry/vite-plugin` for the client bundle — but the CLI
script already covers both modes uniformly, so it is the default.

## Enabling tracing or session replay later

We start with **errors only** (no `tracesSampleRate`, no tracing/replay
integrations) to keep quota and bundle size down. To add performance tracing,
set `tracesSampleRate` and add `Sentry.browserTracingIntegration()` (client)
plus `tracePropagationTargets` on both sides so a request links front → back.
For session replay add `Sentry.replayIntegration()` on the client. Both are
one-line additions to the `Sentry.init` calls in `client.ts` / `server.ts`.
