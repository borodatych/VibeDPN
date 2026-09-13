import { mixpanelClientApi } from './client'
import { mixpanelServerApi } from './server'
import { env } from '@point0/core'

export type MixpanelProps = Record<string, unknown>
/**
 * The fields `MixpanelTrackAuth` forwards on sign-in. `id` and `impersonated` drive identity / super-props; the rest
 * become the Mixpanel People profile (mapped to reserved `$`-props and plain props in `client.ts`). Everything but `id`
 * is optional, so the same shape covers the minimal and the rich case — add a field here when you have more to send
 * (e.g. a `plan` once you add billing).
 */
export type MixpanelUser = {
  id: string
  impersonated?: string
  email?: string
  name?: string
  avatar?: string
  createdAt?: string | Date
  role?: string
  google?: string
  sn?: number
}

/**
 * Side-agnostic Mixpanel surface. `client.ts` and `server.ts` each implement it over their own SDK; `shared.ts` picks
 * the right one. When `enabled` is false (no project token) every method is a no-op.
 *
 * @tags mixpanel
 */
export type MixpanelApi = {
  enabled: boolean
  track: (event: string, props?: MixpanelProps) => void
  identify: (user: MixpanelUser | null) => void
}

// The Point0 compiler replaces this `env.side.define` with just the current side's branch and prunes the other import,
// so the wrong-side SDK never reaches the bundle (see ./README.md → "How it works in code"). Init is side-specific and
// lives in `client.ts` / `server.ts` (`initMixpanelClient` / `initMixpanelServer`) — the entry points are already
// per-side, so there is no shared init.
const mixpanelApi: MixpanelApi = env.side.define({ client: mixpanelClientApi, server: mixpanelServerApi })

/**
 * Track a product-analytics event from anywhere — server or browser. No-op when Mixpanel is disabled (no token). The
 * client attaches the id it already holds; the server attaches the current request's user (`distinct_id`), IP, and user
 * agent. Off-request code (worker / webhook / db hook) has no request — pass `distinct_id` (and `ip`) in `props`.
 *
 * What and where to track is a rule — see `./README.md`.
 *
 * @example
 *   mixpanelTrackEvent('Checkout Started', { provider: 'stripe', plan: 'basic', period: 'month' })
 *
 * @tags mixpanel
 * @related mixpanelIdentifyUser, sentryCaptureError
 */
export const mixpanelTrackEvent = (event: string, props?: MixpanelProps): void => {
  if (!mixpanelApi.enabled) {
    return
  }
  mixpanelApi.track(event, props)
}

/**
 * Tie subsequent events to a user on sign-in, or detach them on sign-out (pass `null`). Mirrors `sentrySetUser`; each
 * is driven from its own module's tracker (`MixpanelTrackAuth` / `SentryTrackAuth`). No-op when Mixpanel is disabled.
 *
 * - Client: `identify` + write the People profile (`people.set` / `set_once`) on sign-in, `reset` on sign-out.
 * - Server: no-op — the Node SDK is stateless and the `distinct_id` is attached per event inside `track`.
 *
 * @tags mixpanel, auth
 * @related mixpanelTrackEvent, sentrySetUser
 */
export const mixpanelIdentifyUser = (user: MixpanelUser | null): void => {
  if (!mixpanelApi.enabled) {
    return
  }
  mixpanelApi.identify(user)
}
