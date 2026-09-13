import { serverEnv } from '@/modules/env/server'
import type { SentryApi } from './shared'
import { getRequestOrUndefined } from '@point0/core'
import '@point0/core/server-only'
import * as Sentry from '@sentry/bun'

let enabled = false

/**
 * Initialize server Sentry (`@sentry/bun`). Call once at startup (`index.server.ts`), after the server env is
 * validated. Off in local, or when no DSN — then `enabled` stays false and every capture is a no-op.
 *
 * @tags sentry
 * @related sentryServerApi
 */
export const initSentryServer = async (): Promise<void> => {
  // Off in local: never report local-dev errors to the real Sentry project, even if a DSN is present.
  enabled = serverEnv.HOST_ENV !== 'local' && !!serverEnv.SENTRY_DSN_SERVER
  if (!enabled) {
    return
  }
  // Errors only: no `tracesSampleRate`, so tracing stays off (see ./README.md to enable it later). `environment`
  // (HOST_ENV) and `release` (SOURCE_VERSION) tag every event so issues are filterable by stage/deploy.
  Sentry.init({
    dsn: serverEnv.SENTRY_DSN_SERVER,
    environment: serverEnv.HOST_ENV,
    release: serverEnv.SOURCE_VERSION,
  })
  // Drain the buffered event queue on shutdown: `lib/shutdown` calls `process.exit()`, which bypasses Sentry's own
  // beforeExit flush, so the last errors before a deploy/scale-down would be lost. Dynamic import avoids a
  // `logger → sentry → shutdown → logger` import cycle (mirrors `initAxiom`).
  const { onShutdown } = await import('@/lib/shutdown')
  onShutdown('sentry', async () => await Sentry.flush(3000))
}

/**
 * Server-side Sentry (Bun runtime), exposed through the shared `SentryApi` shape. `enabled` reflects whether
 * `initSentryServer()` has run. Lives only in the server bundle — on the client build `shared.ts` selects
 * `sentryClientApi` via `env.side.define` and this module (with `@sentry/bun`) is pruned.
 *
 * @tags sentry
 * @related sentryClientApi, sentryCaptureError, initSentryServer
 */
export const sentryServerApi: SentryApi = {
  get enabled() {
    return enabled
  },
  captureException: (error, context) => {
    // Attach the current request's user per-event (not a global `setUser`), so concurrent requests never mislabel each
    // other. `request.cache.me` is populated by `getMe` (auth); absent for anonymous requests and off-request errors.
    const me = getRequestOrUndefined()?.cache.me
    Sentry.captureException(error, {
      ...context,
      ...(me ? { user: { id: me.user.id, email: me.user.email, username: me.user.name } } : {}),
    })
  },
  captureMessage: (message, level) => {
    Sentry.captureMessage(message, level)
  },
  setUser: (user) => {
    Sentry.setUser(user)
  },
}
