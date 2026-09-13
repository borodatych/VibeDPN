import { clientEnv } from '@/modules/env/client'
import { CookieStore } from '@point0/core/cookie-store'
import '@point0/core/client-only'
import mixpanel from 'mixpanel-browser'
import { ms } from 'ms'
import type { MixpanelApi, MixpanelProps, MixpanelUser } from './shared'

let enabled = false

// Original ID Merge: anonymous events live under a generated distinct_id, and only an explicit `alias` → `identify` at
// sign-up links that pre-signup history to the new user — `identify` alone won't back-merge once the id already has
// events (which our server-side "Signed Up" event creates). We alias once per browser, and only for a just-created
// account, so a returning sign-in just identifies. The guard holds the aliased user id across reloads and is cleared on
// sign-out (`reset` then mints a fresh anonymous id, so the next sign-up on this browser links too). It rides a cookie,
// not localStorage, to match mixpanel's own cookie persistence (see init) — both survive restrictive in-app webviews.
const mixpanelAliasedCookie = CookieStore.define<string>('mixpanel-aliased')
const SIGNUP_WINDOW_MS = ms('10m')

const justSignedUp = (user: MixpanelUser): boolean => {
  if (!user.createdAt) {
    return false
  }
  const createdAtMs = new Date(user.createdAt).getTime()
  return Number.isFinite(createdAtMs) && Date.now() - createdAtMs < SIGNUP_WINDOW_MS
}

/**
 * Initialize browser Mixpanel (`mixpanel-browser`). Call once at startup (`index.client.tsx`), after the client env is
 * validated. Off in local, or when no token — then `enabled` stays false and every call is a no-op.
 *
 * @tags mixpanel
 * @related mixpanelClientApi
 */
export const initMixpanelClient = (): void => {
  // Off in local: never send local-dev events to the real Mixpanel project, even if a token is present.
  enabled = clientEnv.HOST_ENV !== 'local' && !!clientEnv.MIXPANEL_PROJECT_TOKEN
  if (!enabled) {
    return
  }
  mixpanel.init(clientEnv.MIXPANEL_PROJECT_TOKEN!, {
    // ⚠️ Data residency: set to the EU host. Mixpanel pins each project to a region at creation, and events sent to the
    // wrong region are silently dropped (no data, no error). This project is EU. When reusing this as a boilerplate for
    // a US-region project, remove `api_host` — the SDK defaults to the US host. See ./README.md.
    api_host: 'https://api-eu.mixpanel.com',
    // SPA page views are tracked by `MixpanelTrackPage` (it reads the Point0 router); `track_pageview: false` so
    // Mixpanel's built-in load-only pageview doesn't double-count. See ./README.md → "Page views".
    track_pageview: false,
    // Cookie, not localStorage: the anonymous distinct_id the alias→identify merge relies on must survive between loads,
    // and some in-app webviews (TikTok, Instagram, ...) restrict or wipe DOM storage while keeping cookies (mixpanel also
    // falls back to a cookie when localStorage is unavailable). `secure_cookie` since the app is https-only outside local.
    persistence: 'cookie',
    secure_cookie: true,
  })
  // Deploy labels stamped on every event as super properties (mirrors Sentry's `environment` / `release`).
  mixpanel.register({
    environment: clientEnv.HOST_ENV,
    ...(clientEnv.SOURCE_VERSION ? { release: clientEnv.SOURCE_VERSION } : {}),
  })
}

/**
 * Browser-side Mixpanel (`mixpanel-browser`), exposed through the shared `MixpanelApi` shape. `enabled` reflects
 * whether `initMixpanelClient()` has run. Lives only in the client bundle — on the server build `shared.ts` selects
 * `mixpanelServerApi` via `env.side.define` and this module (with `mixpanel-browser`) is pruned.
 *
 * @tags mixpanel
 * @related mixpanelServerApi, mixpanelTrackEvent, initMixpanelClient
 */
export const mixpanelClientApi: MixpanelApi = {
  get enabled() {
    return enabled
  },
  track: (event, props) => {
    mixpanel.track(event, props)
  },
  identify: (user) => {
    // No user → sign-out: clear the People profile binding, super properties, and the persisted distinct_id so the next
    // visitor starts fresh. Also drop the alias guard, so a fresh sign-up on this browser links its new anonymous id.
    if (!user) {
      mixpanel.reset()
      mixpanelAliasedCookie.set('')
      return
    }
    // Link this browser's pre-signup anonymous history to the user, once, at sign-up. `alias` maps the current
    // anonymous distinct_id → user.id and MUST run before `identify`; the guard stops it re-firing on later loads.
    if (justSignedUp(user) && mixpanelAliasedCookie.get() !== user.id) {
      mixpanel.alias(user.id)
      mixpanelAliasedCookie.set(user.id)
    }
    mixpanel.identify(user.id)
    // People profile. `$email` / `$name` / `$avatar` are Mixpanel's reserved props (shown in the UI, drive messaging);
    // the rest are plain props for segmentation. Blank fields are omitted so `set` never overwrites with empty values.
    const profile: MixpanelProps = {
      ...(user.email ? { $email: user.email } : {}),
      ...(user.name ? { $name: user.name } : {}),
      ...(user.avatar ? { $avatar: user.avatar } : {}),
      ...(user.role ? { role: user.role } : {}),
      ...(user.google ? { google: user.google } : {}),
      ...(user.sn !== undefined ? { sn: user.sn } : {}),
    }
    mixpanel.people.set(profile)
    // `$created` via set_once so a later sign-in never moves the signup date back.
    if (user.createdAt) {
      mixpanel.people.set_once({ $created: user.createdAt })
    }
    if (user.impersonated) {
      mixpanel.register({ impersonated: user.impersonated })
    } else {
      mixpanel.unregister('impersonated')
    }
  },
}
