---
id: mixpanel
description:
  How Mixpanel is wired (one module, env.side, mixpanelTrackEvent /
  mixpanelIdentifyUser), which env vars you need, and the rule to track only
  through the helpers.
tags: rule, setup, mixpanel
---

# Product analytics with Mixpanel

Product events go to [Mixpanel](https://mixpanel.com). One module —
`@/modules/mixpanel` — inits the right SDK per side and exposes
`mixpanelTrackEvent` and `mixpanelIdentifyUser`.

Page views are tracked automatically (see [below](#page-views)); everything else
you send by hand — there is no error-funnel equivalent. Call
`mixpanelTrackEvent('...')` at the moments you care about (sign-up, subscribe, a
key button). Keep event names stable and human-readable; they are your schema.

## What to track (the rule)

Track meaningful product moments that move a funnel — not render noise, not
every keystroke, and not what `Page Viewed` already covers. Typical events:
`Signed Up`, `Signed In`, `Signed Out`, `Checkout Started`,
`Subscription Activated`. The full rule (naming, props, placement) lives in the
`mixpanelTrackEvent` JSDoc ([shared.ts](./shared.ts)).

Free text the user typed (a search query, an AI question) is worth capturing as
an event prop — it's the best signal for what people actually need — but
truncate it (≈300 chars) and treat it as best-effort, not PII-clean (users can
paste secrets): event prop only, never a user profile.

### Prefer the server

Track an event **server-side whenever it maps to a server endpoint or a state
change and the user is known** — auth completion, payments, subscription
changes, any authenticated mutation. Server delivery is more reliable: immune to
ad-blockers (a developer audience blocks the browser SDK heavily), to redirects,
and to closed tabs, and the payload is authoritative (real amounts, verified
provider, nothing the user can spoof). Concretely here, `Signed Up` /
`Signed In` ride better-auth's `databaseHooks` (one place, every method), and
`Subscription Activated` fires from the subscription state-update on the
inactive→active transition only.

Keep an event **client-side** in two cases:

- **Anonymous, top-of-funnel signals.** The browser SDK keeps a persisted
  anonymous id and merges it into the user on sign-in, so it connects "anonymous
  visitor did X → later signed up". Track these server-side, where an anonymous
  visitor has no identity, and you break that funnel.
- **Client-only context, or no server touchpoint** — page/route, device,
  referrer/UTM, which variant, intent-then-abandon, a pure external-link click
  (e.g. a checkout that's just an outbound URL).

### Request enrichment (server)

On a real request the server helper also attaches, from `request.from`, the
visitor's **IP** and **user agent**. The IP matters: Mixpanel geolocates from
it, and if you don't send one the API falls back to the **calling machine's** IP
— i.e. this server — so every event would resolve to the datacenter. The helper
sends the visitor's IP on-request, and `ip: 0` off-request to **skip**
geolocation rather than poison it. (Mixpanel consumes `ip` for geo and stores
City/Region/Country, not the raw address.)

### Off-request server code

A worker, a webhook, or a db hook runs outside Point0's request scope, so the
helper can't read the current user (or IP) from it — pass `distinct_id` in
`props` to tie the event to a user there. Geolocation is skipped unless you pass
an `ip`.

The auth events are the notable case: they fire from better-auth's
`databaseHooks` (which also run outside the request scope, and after the tx), so
they pass `ip` and user agent **explicitly** — sourced from better-auth's own
data (the `session` row for sign-in, the request context headers for sign-up)
rather than from `getRequestWeak()`. That's the pattern for any hook-based
event: don't rely on the ambient request, read what you need from the hook's own
inputs and pass it.

## How to organise the project in Mixpanel

Mixpanel is simpler than Sentry here: **one project**, one **project token**,
used by both the browser and the server. There is no per-runtime split — client
and server events land in the same project and are told apart by an event
property (e.g. `$lib` is set by the SDKs, or add your own `side`). Stages
(`local` / `dev` / `prod`) are not separate projects either; track an
`environment` property if you need to filter by stage (we don't by default).

Setup once: create the project in Mixpanel, copy its **Project Token** (Settings
→ Project Settings), and put it in `.env` as `MIXPANEL_PROJECT_TOKEN`. That
single token is everything tracking needs.

### Data residency (EU vs US)

A project is pinned to a region when created, and events sent to the wrong
region's host are **silently dropped** — no data, no error. **This project is in
the EU**, so both SDKs are initialised with the EU host:

- **client** (`client.ts`) — `api_host: 'https://api-eu.mixpanel.com'` in the
  `mixpanel.init` options.
- **server** (`server.ts`) —
  `Mixpanel.init(token, { host: 'api-eu.mixpanel.com' })`.

This repo doubles as a **boilerplate**. If you reuse it for a **US**-region
project, **remove those two options** — the SDKs default to the US host. Both
are one-liners next to the init calls, each flagged with a `⚠️` comment.

## How it works in code

The side-split (`client.ts` / `server.ts` / `shared.ts` over `env.side.define`),
the compiler pruning that keeps each SDK out of the other side's bundle, and the
no-token → off gate all work exactly as in
[sentry](../sentry/README.md#how-it-works-in-code). What's Mixpanel-specific is
the two SDK shapes, hidden behind one surface:

- **Client** (`mixpanel-browser`) is **stateful** — it persists a `distinct_id`
  (in `localStorage`), so `track` needs no id and `identify` / `reset` change
  who subsequent events belong to.
- **Server** (`mixpanel` Node) is **stateless** — every `track` must carry a
  `distinct_id`. `mixpanelServerApi.track` reads the current request's user
  (`request.cache.me`, set by `getMe`) and attaches it per event; anonymous or
  off-request events go in without one. There is no server `identify`/`reset`.

To report something, use the helpers (import from `@/modules/mixpanel/shared`):

```ts
import { mixpanelTrackEvent } from '@/modules/mixpanel/shared'

mixpanelTrackEvent('Subscribed', { plan: 'basic' }) // props are sent as Mixpanel event properties
```

## User identity

`mixpanelIdentifyUser` is wired from **[`MixpanelTrackAuth`](./track-auth.tsx)**
(mounted once in `app.client.tsx`), the Mixpanel counterpart to Sentry's
`SentryTrackAuth`. On sign-in it calls `mixpanel.identify(user.id)` and writes
the **People profile** with `mixpanel.people.set`: `$email`, `$name`, `$avatar`
(Mixpanel's reserved profile props — shown in the UI and used for messaging),
plus `role`, the Google email (`google`) and `sn` for segmentation. `$created`
goes through `set_once`, so a later sign-in never moves the signup date. On
sign-out it calls `mixpanel.reset()` to clear the persisted id, the profile
binding, and super properties. Impersonation is tracked as a super property.

`MixpanelTrackAuth` passes the plain domain fields (`email`, `name`, `avatar`,
...); the mapping to reserved `$`-props lives in `client.ts`. To add a field,
extend `MixpanelUser` (`shared.ts`), fill it in `MixpanelTrackAuth`, and map it
in `client.ts` — e.g. a `plan` once you add billing.

This is client-only — the server is stateless and resolves the user per event in
`track`, so `mixpanelIdentifyUser` is a no-op there. The browser SDK is the part
an ad-blocker can drop: events still arrive server-side carrying a
`distinct_id`, but the profile is written here, so a blocked client just leaves
a thinner profile (no email/name). Move the `people.set` into
`mixpanelServerApi` (off the `databaseHooks`, like the auth events) if you need
it ad-block-proof.

**The full record is sent on purpose** — email, name, avatar. This deliberately
does **not** follow the logger's PII redaction: logs stream to stdout and leak
into traces, whereas an analytics profile is exactly where you want to recognise
the user. Sentry mirrors it (`email` / `username` on its user); only the logger
stays redacted.

## Page views

A `Page Viewed` event fires on the initial load and on every client-side
navigation — Mixpanel's built-in `track_pageview` is **off** (it can't see SPA
route changes), so [`MixpanelTrackPage`](./track-page.tsx) handles it. It's
mounted once next to `MixpanelTrackAuth` in `app.client.tsx` (inside `<Router>`)
and reads the Point0 router location with `useLocation` from
`@point0/core/navigation`, so the event fires on the page actually shown — not
at navigation start.

Each event carries `path` (the concrete pathname) and `route` (the matched
template, e.g. `/users/:id`, for grouping). Query and hash are excluded on
purpose — keying on `path` + `route` keeps query-only changes (`?tab=...`) and
in-page anchors from spamming pageviews, and avoids leaking query params.

`useLocation` (not `useOnNavigate`) is the right primitive: it reports the
committed location and includes the first load, whereas `useOnNavigate` fires at
the start of a transition and skips the initial page — that hook is for
transition side-effects with cleanup (it backs `NProgress`).

**Per-tool, not shared.** Each analytics tool ships its own self-contained
`*TrackPage` (Google will add a `GATrackPage` in its module). They each
subscribe to the router independently — there's no shared page-view wiring, and
since they render no children there's no re-render cost to worry about. The
duplicated location read is a few lines; keeping each tool's tracking inside its
own module is worth more than deduping it.

## Deploy labels

Every event carries `environment` (`HOST_ENV`) and `release` (`SOURCE_VERSION`)
— the same pair Sentry sets as its `environment` / `release` — so you can slice
analytics by stage and deploy. On the **client** they are registered once as
super properties (`mixpanel.register`); on the **server**, where the stateless
SDK has no super properties, they are merged into every `track` call. `release`
is dropped when `SOURCE_VERSION` is empty.

## Rule: track only through the helpers

Never import `mixpanel-browser` / `mixpanel` directly in features. Always go
through `mixpanelTrackEvent` / `mixpanelIdentifyUser` from
`@/modules/mixpanel/shared`. They respect the disabled state (no token → no-op),
keep the side-split intact, and are the single place to swap providers or add
another analytics tool later.

## Environment variables

- **`MIXPANEL_PROJECT_TOKEN`** — the project token (in `@/modules/env`'s shared
  shape, so it's available on both sides and reaches the browser — injected into
  the page at runtime, not baked into the bundle — it is **public by design**,
  like the Sentry client DSN). Required outside local (`HOST_ENV != local`).
  Mixpanel is **hard-disabled in local** (`HOST_ENV === 'local'`) regardless of
  the token, so a local checkout never sends to the real project — to test it
  locally, flip the `enabled` gate in `client.ts` / `server.ts`.

That is the only variable tracking needs — the running app reads nothing else.

`MIXPANEL_API_SECRET` is **not read by the app**: it authenticates Mixpanel's
Query / data-export API (and the legacy import endpoint for events older than 5
days), which the app never calls. It's an **agent/analysis** key — it lives in
`env.agents.example` (→ `.env.agents`, gitignored), not `env.example`. With it a
human or agent can pull product analytics to inspect behavior, e.g.
`GET https://eu.mixpanel.com/api/2.0/segmentation` authenticated as the secret
(use the `eu.` host for an EU project — see Data residency above).
