---
tags: auth
---

# Auth

The biggest module in the app. It's a thin layer over **better-auth** plus the
Point0 glue that makes "who is the current user, and may they see this?" a
one-liner everywhere else. Provider config (providers, fields, email flows)
lives in `server.ts`; the auth UI in `components/` (forms, the sign-in drawer,
OAuth buttons) and `pages/` (sign-in/up, sign-out, password reset, profile).

## The two instances

- **`server.ts`** — the `betterAuth()` server instance (`authServer`) and, more
  importantly, **`getMe`**: the canonical server-side session read. Cached per
  request, so prefer it over `authServer.api.getSession`. `getMeFresh` bypasses
  the cache (use after you mutate role/links and the next read must see it);
  `getMeCached` peeks at what `getMe` already stored without running it. The
  user shape it returns (`Me`) is better-auth's user plus an `admin` flag.
- **`client.ts`** — the browser client (`authClient`). **Reserved for
  mutations** (sign in/out, link, change password). Never read the session
  through it — client reads go through `getMeQuery` (`api.ts`) so all caching is
  uniform; the proxy even throws if you touch it on the server.

## Gating — `plugins.ts`

Never check `me` by hand in a loader. Use these Point0 plugins:

- `mePlugin` — building block: loads `me` into ctx/props and prefetches
  `getMeQuery`. You rarely use it directly.
- `authorizedOnlyPlugin` — throws `UNAUTHORIZED` for anonymous; after it `me` is
  non-null.
- `redirectUnauthorizedPlugin` / `redirectAuthorizedPlugin` — same, but redirect
  to `signIn` / `home` instead of throwing. Use these on user-facing pages.
- `adminOnlyPlugin` — throws `FORBIDDEN` for non-admins; already applied by
  `adminBase`, so admin points get it for free.

## The non-obvious bits

- **`server-linking-fix.ts`** — on link, better-auth copies the provider's name
  and image but never its email, so `googleEmail` would stay empty. This
  re-fetches the Google profile after link/unlink to keep it in sync. Wired in
  via `databaseHooks` in `server.ts`. Failures are swallowed (`trySync...`) — a
  link must not fail over this.
- **Email verification** — three ways an address becomes verified, and they all
  come down to the same proof: someone reached that mailbox. The verification
  email (sent on sign-up, or on demand from the profile) is the plain one.
  Signing in with Google covers it too — better-auth trusts the provider's
  `email_verified` when the address matches. The third is ours, in
  `server-linking-fix.ts`: linking Google from the profile is the same proof,
  but better-auth skips it on that path. Nothing is gated on `emailVerified` yet
  — it exists for when something needs to be.
- **Impersonation** — an admin can sign in as a user. The buttons and the
  impersonate/unimpersonate pages live in `features/user/admin`, but the session
  flag (`session.impersonatedBy`) surfaces through `getMe`/`getMeQuery` here,
  and the per-tool trackers `SentryTrackAuth` / `MixpanelTrackAuth` (each in its
  own module) forward it to Sentry / Mixpanel.
- **`error.ts`** — maps better-auth's terse error codes to readable messages and
  adapts `BetterFetchError` into our `Error0`.
