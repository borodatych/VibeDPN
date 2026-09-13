import { clientEnv } from '@/modules/env/client'
import type { SentryApi } from './shared'
import '@point0/core/client-only'
import * as Sentry from '@sentry/react'

let enabled = false

/**
 * Initialize browser Sentry (`@sentry/react`). Call once at startup (`index.client.tsx`), after the client env is
 * validated. Off in local, or when no DSN — then `enabled` stays false and every capture is a no-op.
 *
 * @tags sentry
 * @related sentryClientApi
 */
export const initSentryClient = (): void => {
  // Off in local: never report local-dev errors to the real Sentry project, even if a DSN is present.
  enabled = clientEnv.HOST_ENV !== 'local' && !!clientEnv.SENTRY_DSN_CLIENT
  if (!enabled) {
    return
  }
  // Errors only: no `browserTracingIntegration` / `replayIntegration` and no `tracesSampleRate`, so tracing and replay
  // stay off. Add them here (and bump the quota) when you want performance or session replay — see ./README.md.
  // `environment` (HOST_ENV) and `release` (SOURCE_VERSION) tag every event so issues are filterable by stage/deploy.
  Sentry.init({
    dsn: clientEnv.SENTRY_DSN_CLIENT,
    environment: clientEnv.HOST_ENV,
    release: clientEnv.SOURCE_VERSION,
  })
}

/**
 * Browser-side Sentry, exposed through the shared `SentryApi` shape. `enabled` reflects whether `initSentryClient()`
 * has run. Lives only in the client bundle — on the server build `shared.ts` selects `sentryServerApi` via
 * `env.side.define` and this module (with `@sentry/react`) is pruned.
 *
 * @tags sentry
 * @related sentryServerApi, sentryCaptureError, initSentryClient
 */
export const sentryClientApi: SentryApi = {
  get enabled() {
    return enabled
  },
  captureException: (error, context) => {
    Sentry.captureException(error, context)
  },
  captureMessage: (message, level) => {
    Sentry.captureMessage(message, level)
  },
  setUser: (user) => {
    Sentry.setUser(user)
  },
}
