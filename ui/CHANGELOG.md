# Changelog

Boilerplate changes, release by release — newest first. Each entry says what
changed and, under **Migration notes**, what an existing app has to do by hand
when pulling the update (the how-to lives in
[docs/updating.md](./docs/updating.md)).

## Unreleased

## v0.1.23 — 2026-08-10

- `@point0/*` bumped to `^0.3.10` — the socket rework release. What it means for
  an app built on this boilerplate: **enroll is a guarantee** (a room granted by
  an `.enroller`, like this app's `userSpace`/`sessionSpace`, cannot be dropped
  from the client — an open channel means the personal room is subscribed),
  `onEnter`/`onLeave` are room events with a `reason`, `onDisconnect` fires on
  transport loss too, and the server closes connections with `kill` (`kick` only
  revokes rooms). Also in 0.3.10: a chunk that fails to load on a flaky network
  retries in place before surfacing an error, and the server's `idleTimeout`
  defaults to 255 s instead of Bun's 10.
- **The auth hooks now address rooms, not identities.** A session death used to
  push into the session's room but `refresh` the channel by
  `{ $identity: { sessionId } }` — a scan over every connection. Enrollment
  being a guarantee makes the room itself the exact set of the session's live
  connections, so both hooks now hit the same hot address:
  `sessionSpace.refresh({ room: { sessionId } })` on a session death,
  `userSpace.refresh({ room: { userId } })` on a ban. The socket README's
  addressing rules are updated to match: admin commands ride rooms too.

**Migration notes**

- `bun install` — `@point0/*` `^0.3.10`.
- If you copied the auth hooks into code of your own, mirror the rewrite: any
  `appChannel.refresh({ $identity: … })` whose selection matches an enrolled
  space's room is better written as `space.refresh({ room: … })`.
- If you added socket callbacks of your own: `onEnter`/`onLeave` props now carry
  `rooms` (always an array) and a `reason`; a channel-level `kick` no longer
  exists — closing connections from the server is `kill`.

## v0.1.22 — 2026-08-08

- `@point0/*` bumped to `^0.3.9` — the release that fixes a **native memory leak
  on Linux** (~1 KB per request: the framework seeded ~20 throwaway `Error`
  sentinels into every request's state; they are shared markers now). If your
  app's container RSS climbed steadily between deploys, this is why. The same
  release makes `@point0/compress` propagate body errors and client cancels
  instead of hanging the response.
- The heartbeat worker now gates **both** knobs off `HOST_ENV !== 'local'`:
  `schedule.enabled` (whether this machine asks the database for the cron) and
  `work.enabled` (whether it executes jobs). Gating only the schedule let a
  local machine execute a cron persisted by another environment on a shared
  database.

**Migration notes**: `bun install` after pulling. If you copied the heartbeat
pattern into workers of your own, add the same `work: { enabled: … }` gate.

## v0.1.21 — 2026-08-07

- `@point0/*` bumped to `^0.3.8`. The one that matters if you run
  `point0 dev --hot`: hot reload flattens your modules into a store before
  running them and used to name every copy `.tsx`, where a leading `<` opens a
  JSX tag — so a plain generic arrow (`const identity = <T>(x: T): T => x`) or a
  `<string>x` assertion in a `.ts` file failed the dev server on boot, while the
  same file compiled fine in `dev` and `build`. If you worked around that by
  writing `function` instead of an arrow, the arrow works again. Also in 0.3.8:
  `.mts`/`.cts` files compile, a syntax error reads as a syntax error instead of
  turning the file into a module with no exports, and the compiler reports what
  it could not do instead of dropping it.
- No boilerplate code changed here. The whole suite — unit, dom, int, and e2e
  against a real build — is green on the new version.

**Migration notes**

- `bun install` — `@point0/*` `^0.3.8`. Nothing else to do by hand.

## v0.1.20 — 2026-08-06

- `@point0/*` bumped to `^0.3.7`. Two things in it matter for an app built on
  this boilerplate. Point0's socket layer is now marked **experimental** in its
  docs — the design is settled, the implementation under it still needs a
  refactor, so it is the one part of the framework where a bug or an awkward
  edge is expected. Nothing in the socket code you already have changes. And a
  save made right after `point0 dev` came up is no longer lost: dev used to
  spawn its server children before its watchers were live, so an edit in that
  window produced no event and no error, and you had to save again.
- No boilerplate code changed here. The whole suite — unit, dom, int, and e2e
  against a real build — is green on the new version.

**Migration notes**

- `bun install` — `@point0/*` `^0.3.7`. Nothing else to do by hand.

## v0.1.19 — 2026-08-03

Written after the fact: the tag was cut but its notes were not, and the tree it
points at still calls itself `v0.1.18`. What that tag carries, from the commits:

- `@point0/*` on `^0.3.5`, and auth over sockets: a socket module
  (`src/modules/socket/`) with its own channel, so a session change in one tab
  reaches the others instead of leaving them signed in.
- A build has no env, so the logger no longer demands one.
- Tailwind housekeeping: arbitrary values that had a scale step, a class that
  did nothing, and classname order.

**Migration notes**

- `bun install` — `@point0/*` `^0.3.5`. New files under `src/modules/socket/`.

## v0.1.18 — 2026-07-31

- `@point0/*` bumped to `^0.3.3` — the sockets-and-subscriptions release — and
  `@1gr14/error0` to `^0.4.8`.
- The app channel: `src/lib/channel.ts` declares an open socket channel — the
  identity is `{ userId: string | null }`, `null` for anonymous visitors, so
  every client connects. One `<appChannel.Connection gate={false}>` wraps the
  routes in `app.client.tsx`.
- New-idea broadcast: `ideaCreateMutation` pushes
  `{ sn, title, authorName, authorId }` to every connected client through
  `ideaCreatedHandler`; `IdeaCreatedToastListener` shows an info toast with an
  Open action — except on the author's own devices, which recognize their user
  id in the push and stay silent. Covered end to end by
  `idea-toast.e2e.test.ts`.
- The socket backplane rides the same Postgres the app already runs
  (`engine.ts`: `socket: true` + `@point0/engine/backplane/postgres` over
  postgres.js — LISTEN/NOTIFY bus, unlogged KV table; the Prisma-flavored
  `?schema=` URL param is stripped for that client). `postgres` joins the direct
  dependencies.
- `AppError` gains `preventRetryPlugin` — error0's "don't try this again" flag;
  Point0's queries and socket reconnects honor it over the wire.

**Migration notes**

- `bun install` — new direct dependency `postgres`; `@point0/*` `^0.3.3`,
  `@1gr14/error0` `^0.4.8`.
- New files to copy: `src/lib/channel.ts`,
  `src/features/idea/components/created-toast.tsx`,
  `src/features/idea/test/idea-toast.e2e.test.ts`. Edited: the
  `ideaCreatedHandler` + push in `src/features/idea/api.ts`, the
  `<appChannel.Connection>` wrap in `src/app.client.tsx`, the `socket` +
  `backplane` block in `src/engine.ts`, `preventRetryPlugin` in
  `src/lib/error.ts`.

## v0.1.17 — 2026-07-20

- `@point0/*` bumped to `^0.2.8` and `@1gr14/route0` to `^0.3.0`.
- A route's path params now carry one descriptor each — `{ required, type }`,
  plus `values` when the param is restricted to a set — reachable as
  `route.params.<name>` at runtime and `ParamsDefinition<T>['<name>']` in types.
- The generated OpenAPI document builds its path templates from the route's
  tokens, so a param's value constraint or a trailing `?` no longer leaks into
  them: `/api/posts/:kind(new|top)/:id` was documented as
  `/api/posts/{kind}(new|top)/{id}`, and `/api/x/:id?` as `/api/x/{id}?`. A
  restricted param also reaches the spec as a real JSON Schema `enum`.

**Migration notes:** none — nothing in the boilerplate reads the changed
surface. If your own code calls route0's `getParamsValues()` or uses the
`ParamsValues` / `ParamsAllowedValues` types, they are gone: read
`route.params.<name>.values` and `ParamsDefinition<T>['<name>']['values']`
instead.

## v0.1.16 — 2026-07-20

- `@point0/*` bumped to `^0.2.7` and `@1gr14/route0` to `^0.2.0`.
- Page routes are now matched by route0 rather than by wouter's own path parser.
  Previously a page's route was handed to wouter as a raw string and re-parsed
  with `regexparam`, a second matcher running beside the one point0 uses
  everywhere else; layouts already used route0's real `RegExp`, and pages now do
  too. The two only agreed for plain routes.
- route0 0.2 adds params constrained to a value set — `:locale(ru|en)` and
  `:locale(ru|en)?` — enforced in matching, building, schema validation, the
  emitted JSON Schema and route ordering, and narrowed to the literal union at
  the type level. It also fixes the route ordering that let an optional leading
  param swallow every single-segment top-level route: with `/:locale?` declared
  alongside `/:locale?/author`, the URL `/author` used to resolve to the first
  with `locale='author'`.

**Migration notes**

- Nothing to do by hand for a typical app: bump the deps, reinstall, and
  regenerate. No config, schema or file-layout change.
- Two route0 behaviours became stricter and now throw at creation instead of
  degrading silently. A route definition that names the same param twice
  (`/:a/:a`) is rejected — previously the second occurrence overwrote the first,
  so one of the two segments could never be filled independently. A malformed
  `:`-segment is rejected too, where it used to become a literal segment that
  matched nothing. If an app has either, it was already broken; the error now
  says so and names the definition.
- Route ordering changed for routes with an optional leading param. If an app
  declares one, re-check which route wins for the URLs it shares with its own
  prefix — a tail naming a finite set of values (a static segment or a
  constrained param) now takes precedence, while a plain `:param` tail does not.

## v0.1.15 — 2026-07-17

- `better-auth` bumped to `^1.6.23` (from `^1.6.9`), which closes a real account
  takeover in the OAuth sign-in path. On 1.6.9, someone could register with a
  victim's email and never verify it; when the victim later signed in with
  Google, better-auth linked their Google identity straight into the attacker's
  row — leaving the attacker with a working password on the victim's account.
  1.6.16+ refuses that implicit link unless the local email is already verified
  (`accountLinking.requireLocalEmailVerified`, on by default, and unconditional
  from the next minor). `trustedProviders` never guarded this — the old check
  only asked whether the _provider_ had verified the address, which Google
  always has.
- Linking Google from the profile now verifies the account's email, when Google
  vouches for that exact address. better-auth already does this when you sign
  _in_ with Google, but skips it on the explicit link path; the same proof
  either way, so `server-linking-fix.ts` closes the gap. A Google account on
  some other address, or one Google itself hasn't verified, still proves
  nothing.
- The profile's Email section shows whether the address is verified and offers
  to send the verification email again. better-auth rate-limits that endpoint to
  3 requests a minute per IP (in production only), and the button holds a
  matching cooldown.
- Changing your email now asks the address you're changing _away_ from, when it
  was verified: confirming there mints a second link to the new address, and the
  change lands only once both mailboxes have answered. A stolen session alone no
  longer walks an account away, and the owner learns of the attempt. An
  unverified address proves nothing, so it still gets the single-email flow.
- `sendVerificationEmail` no longer overwrites the caller's `callbackURL`. It
  clobbered every link with a `?success=` the app never read, so a verification
  email from `changeEmail` silently landed on the home page instead of the
  profile. Callers that want a specific landing pass `callbackURL` themselves.

**Migration notes:** bump `better-auth` to `^1.6.23` and `bun install`. The
takeover fix has a visible edge: a user who signed up by password and never
verified now gets `account not linked` when they try to sign in with Google —
they verify by email first (the new profile button), or sign in by password and
link Google from the profile, which verifies them outright. If your app grants
anything off `emailVerified`, note that linking Google is now a third way to
earn it. Apps that call `authClient.sendVerificationEmail` or
`authClient.changeEmail` and relied on landing somewhere specific must pass
`callbackURL` — nothing did so implicitly before either, it was just being
overwritten.

## v0.1.14 — 2026-07-14

- Built on Point0 0.2.6 — fixes scroll restoration. Reloading a scrolled page no
  longer flashes at the top before jumping back to where you were (a document
  load is restored by the browser, before the first paint — Point0 now hands it
  the mode on the way out instead of holding `'manual'` for the page's whole
  life), and `.scrollPosition()` finally restores a custom scroll container,
  which it never did. A restore also stops animating under
  `scroll-behavior: smooth`.
- `bun run init` now deletes `install-point0.js` along with `init/` and `dev/`.
  It is a boilerplate-internal tool for developing Point0 itself against Start0,
  so a generated app has no use for it. The script also lost its hardcoded
  checkout path — it derives the main checkout from git, and takes
  `POINT0_MAIN_CHECKOUT` / `POINT0_LOCAL_REGISTRY` overrides.
- `lint-staged` no longer spawns the removed `tsgo` binary on every commit (it
  died with `ENOENT`); the type-check hook goes through `bun run types`, the one
  place that knows how this repo type-checks.

**Migration notes:** bump `@point0/*` to `^0.2.6` and `bun install`. Nothing
else is required — the scroll fixes are behavioural and need no code change. If
your app still carries `install-point0.js` (copies made before this release kept
it), it is safe to delete.

## v0.1.13 — 2026-07-13

- Built on Point0 0.2.5 — fixes the SSR hydration mismatch where server- and
  client-rendered Radix ids diverged (the app now renders at its own `#root`
  root, so `useId` matches). `react`/`react-dom` bumped to `^19.2.7` to match
  Point0's peer.
- Prisma migrations squashed from two into a single `init`.
- CLI/init output tidied: spinner messages drop their trailing ellipsis (the
  spinner animates its own dots), `Next steps` no longer prints `cat .env`, and
  the Environment step no longer tells you to copy env or regenerate the auth
  secret — `bun run init` already did both. Stray single-character ellipses
  replaced with plain `...` across docs and comments.

**Migration notes:** bump `@point0/*` to `^0.2.5` and `react`/`react-dom` to
`^19.2.7`, then `bun install` (Point0 0.2.5 also adopts React 19's native
`<title>`/`<meta>` hoisting — see its changelog). The migration squash is for
fresh installs: an existing app whose database already ran the old migrations
should skip the migrations hunk (don't rewrite applied history), or reconcile
with `prisma migrate resolve`.

## v0.1.12 — 2026-07-13

- `docs/setup.md`: the Init step now notes inline that `bun create start0`
  already ran `bun run init` for you, and the Environment step drops the
  redundant `cp env.example .env` (init already creates `.env`).

**Migration notes:** none — docs only.

## v0.1.11 — 2026-07-13

- The init script's closing line is now just `<App> is ready.` — the trailing
  "Happy hacking! ♥" is gone. Paired with `1gr14` CLI 0.3.7, which no longer
  prints its own outro on top after running init, so the "ready" line is the
  single sign-off instead of a duplicate.

**Migration notes:** none — cosmetic, and `init/` isn't part of a created app.

## v0.1.10 — 2026-07-13

- Prisma schema and migrations moved out of the root `prisma/` dir into the
  `prisma` module: `src/modules/prisma/{schema.prisma,migrations/}`. The
  generated client path (`src/generated/prisma`) is unchanged, so no imports
  move. `prisma.config.ts` now points its `schema` and `migrations.path` at the
  module, and the Dockerfile copies just those two paths into the runtime image.

**Migration notes:** the update diff moves the files for you. After applying it,
run `bun run prisma:generate` and check `prisma.config.ts` points at
`src/modules/prisma`. No database or migration changes.

## v0.1.9 — 2026-07-10

- Built on Point0 0.2.4. Every cross-boundary protocol string (the `x-point0-*`
  headers, the `/_point0/` path family, the injected SSR globals) now lives in
  per-package `protocol.ts` modules; the generated endpoint meta carries the
  kebab-case URLs the server actually mounts, and the OpenAPI document spells
  its header parameters lowercase. `getLocation()`/`getSearch()` now answer in
  page loaders and RSC server components, and two navigation bugs are fixed
  (empty `dehydratedState` when the request carried no `Referer`, and a literal
  `/undefined/...` pathname when the location had no origin). Upstream libs
  bumped along: `@1gr14/route0` 0.1.3 (fixes the TS2590 type explosion at 500+
  routes), `@1gr14/error0` 0.4.7, `@1gr14/flat` 0.1.4.

**Migration notes:** bump `@point0/*` to `^0.2.4` and `bun install`. No hand
edits — the wire-contract renames are internal to Point0 (old deployed clients
recover via the deploy-invalidation navigation).

## v0.1.8 — 2026-07-10

- Built on Point0 0.2.3 — the big streaming/RSC release. Point0 now streams SSR
  as one document (the shell flushes immediately, slow parts stream in), server
  loaders can return React elements (RSC "elements as data"), `defer()` streams
  a slow subtree as a hole in the same response, and a still-resolving promise
  can be handed straight to an island prop. Per-point `.ssr()` / `.clientOnly()`
  split the SSR-execute and client-only-render switches, and query-family reads
  go over GET (with a POST fallback) so a CDN can cache them. The boilerplate
  adopts the two new middleware packages — `@point0/compress` (streaming
  brotli/gzip/zstd) and `@point0/cache-control` (correct `Cache-Control` per
  response variant) — replacing the local `cache-headers` helper. (Point0
  0.2.0–0.2.2 never reached npm; 0.2.3 is the first published build of that line
  — see the Point0 changelog.)

**Migration notes:** bump `@point0/*` to `^0.2.3` and `bun install`. Two hand
changes. (1) `createQueryClient` no longer takes a `QueryClient` instance —
Point0 constructs it so its defaults merge with yours; call
`createQueryClient()` (or pass a `() => QueryClientConfig` to customize) and
drop the `() => new QueryClient()` argument (passing an instance now throws).
(2) Swap the local response-header middleware for the new packages: replace
`.middleware(cacheHeadersMiddleware)` with `.middleware(compress())` +
`.middleware(cacheControl())` and delete `src/lib/cache-headers.ts`.

## v0.1.7 — 2026-07-03

- Built on Point0 0.1.12. Over 0.1.10 this brings router-managed scroll
  restoration (a push scrolls to the top or the target `#hash`, back/forward
  restores the remembered position — persisted across reloads via
  `sessionStorage`), relative `navigate.to(...)` resolution (a string target
  resolves against the current page the way a browser resolves an `<a href>`),
  and a dev-proxy fix that forwards origin `Content-Encoding` transparently so
  gzip/brotli compression no longer serves a blank page in dev. 0.1.12 itself is
  an internal test-lint cleanup with no runtime or API change. All additive —
  nothing in an app needs adapting beyond the bump.

**Migration notes:** bump `@point0/*` to `^0.1.12` and `bun install`.

## v0.1.6 — 2026-07-03

- Built on Point0 0.1.10 (a docs-only fix on top of 0.1.9 — package code is
  unchanged from 0.1.7, so nothing in an app needs adapting beyond the bump).

**Migration notes:** bump `@point0/*` to `^0.1.10` and `bun install`.

## v0.1.5 — 2026-07-03

- Built on Point0 0.1.9 (a docs-facelift release — package code is unchanged
  from 0.1.7, so nothing in an app needs adapting beyond the bump).
- Prose/comments: brand names (Point0, Start0, Error0) are now capitalized in
  the docs and code comments — no behavior change.

**Migration notes:** bump `@point0/*` to `^0.1.9` and `bun install`.

## v0.1.4 — 2026-07-01

- Built on Point0 0.1.7.
- `bun run init`: the "Next steps" now print the correct `cd`. It uses the
  directory `1gr14 create` hands over (via `S_1GR14_CREATE_DIR`) instead of
  guessing from the script's own cwd — which had it printing a wrong `cd ..`
  (the `init` script does `cd init` first, so the cwd is never the app root, and
  Bun sets no `INIT_CWD`). Run standalone it prints no `cd` — you're already in
  the app root. Needs the `1gr14` CLI `>= 0.3.4` for the `cd <dir>` hint; older
  CLIs just omit the line.
- Docs: `bunx 1gr14 update` → `bunx 1gr14@latest update`.

**Migration notes:** bump `@point0/*` to `^0.1.7` and `bun install`.

## v0.1.3 — 2026-07-01

- Built on Point0 0.1.6.

**Migration notes:** bump `@point0/*` to `^0.1.6` and `bun install`.

## v0.1.2 — 2026-07-01

- Built on Point0 0.1.5.
- `bun run init`: the final "next steps" now lead with `cd <dir>`, and a
  Windows-locked `init/` folder is tolerated (left in place) instead of crashing
  the run. Setup docs refreshed to match.

**Migration notes:** bump `@point0/*` to `^0.1.5` and `bun install`.

## v0.1.1 — 2026-06-30

- Built on Point0 0.1.4.
- Auth error handling: a better-auth `APIError` (a bad/revoked credential, a
  banned user) now surfaces with its real HTTP status (e.g. `401`) instead of a
  blanket `500`. better-call hides the class behind base `Error`, so it's
  matched by its instance `.name` + property shape.

**Migration notes:** bump `@point0/*` to `^0.1.4` and `bun install`. If you kept
the stock `src/modules/auth/error.ts`, the update diff re-applies the `APIError`
branch; a customized copy needs it merged by hand.

## v0.1.0 — 2026-06-30

- Initial boilerplate: Point0 app with auth (email/password + Google), admin,
  forms, CRUD, tests, Docker/Railway setup.
- One-time `bun run init` setup script (rename, `.env` + secret, `start0`
  remote).
- Delivery via [1gr14.dev](https://1gr14.dev): `bun create start0`, zip
  download, or GitHub collaborator access.
- Built on Point0 0.1.3.

**Migration notes:** first release — nothing to migrate.
