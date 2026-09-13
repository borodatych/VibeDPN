import { serverEnv } from '@/modules/env/server'
import { getRequestOrUndefined } from '@point0/core'
import '@point0/core/server-only'
import Mixpanel from 'mixpanel'
import type { MixpanelApi, MixpanelProps } from './shared'

let enabled = false
let mixpanel: ReturnType<typeof Mixpanel.init> | null = null
// Deploy labels merged into every event (mirrors Sentry's `environment` / `release`). The Node SDK is stateless, so
// super properties don't exist — unlike the browser, where these are registered once. Filled in by `initMixpanelServer`.
let baseProps: MixpanelProps = {}

/**
 * Initialize server Mixpanel (the `mixpanel` Node SDK). Call once at startup (`index.server.ts`), after the server env
 * is validated. Off in local, or when no token — then `enabled` stays false and every call is a no-op.
 *
 * @tags mixpanel
 * @related mixpanelServerApi
 */
export const initMixpanelServer = (): void => {
  // Off in local: never send local-dev events to the real Mixpanel project, even if a token is present.
  enabled = serverEnv.HOST_ENV !== 'local' && !!serverEnv.MIXPANEL_PROJECT_TOKEN
  // ⚠️ Data residency: set to the EU host. Mixpanel pins each project to a region at creation, and events sent to the
  // wrong region are silently dropped (no data, no error). This project is EU. When reusing this as a boilerplate for a
  // US-region project, drop the `host` option — the SDK defaults to the US host. See ./README.md.
  mixpanel = enabled ? Mixpanel.init(serverEnv.MIXPANEL_PROJECT_TOKEN!, { host: 'api-eu.mixpanel.com' }) : null
  baseProps = {
    environment: serverEnv.HOST_ENV,
    ...(serverEnv.SOURCE_VERSION ? { release: serverEnv.SOURCE_VERSION } : {}),
  }
}

/**
 * Server-side Mixpanel (Node SDK), exposed through the shared `MixpanelApi` shape. `enabled` reflects whether
 * `initMixpanelServer()` has run. The Node SDK is stateless — it has no `identify`/`reset` and needs a `distinct_id` on
 * every event — so `track` reads the current request's user (`request.cache.me`, set by `getMe`) and attaches it;
 * off-request or anonymous events go in without one. Lives only in the server bundle (the client build prunes it via
 * `env.side.define`).
 *
 * @tags mixpanel
 * @related mixpanelClientApi, mixpanelTrackEvent, initMixpanelServer
 */
export const mixpanelServerApi: MixpanelApi = {
  get enabled() {
    return enabled
  },
  track: (event, props) => {
    // Send the visitor's `ip` so Mixpanel geolocates from it, not from this server's IP; `0` off-request skips geo. User
    // and user agent ride along too; `props` override.
    const request = getRequestOrUndefined()
    const me = request?.cache.me
    const from = request?.from
    mixpanel?.track(event, {
      ...baseProps,
      ip: from?.ip ?? 0,
      ...(me ? { distinct_id: me.user.id } : {}),
      ...(from?.userAgent ? { $user_agent: from.userAgent } : {}),
      ...props,
    })
  },
  // Stateless SDK: identity is carried per event by `track`, so there is nothing to set or clear here.
  identify: () => {},
}
