import { Error0 } from '@1gr14/error0'
import { causePlugin } from '@1gr14/error0/plugins/cause'
import { codeStatusPlugin } from '@1gr14/error0/plugins/code-status'
import { flatOriginalPlugin } from '@1gr14/error0/plugins/flat-original'
import { metaPlugin } from '@1gr14/error0/plugins/meta'
import { redirectPlugin } from '@1gr14/error0/plugins/point0-redirect'
import { preventRetryPlugin } from '@1gr14/error0/plugins/prevent-retry'
import { betterAuthErrorPlugin } from '@/modules/auth/error'
import { expectedPlugin } from '@1gr14/error0/plugins/expected'
import { levelPlugin } from '@1gr14/error0/plugins/level'
import { responsePlugin } from '@1gr14/error0/plugins/response'
import { stackPlugin } from '@1gr14/error0/plugins/stack'
import { POINT0_ERROR_CODES_MAP } from '@point0/core'

/**
 * Project error class. Throw `AppError` (instead of `Error`) anywhere a controllable, serializable error is wanted.
 *
 * A `redirect` cause short-circuits Point0 navigation; other errors are surfaced by `ErrorComponent` /
 * `ErrorPageComponent`.
 *
 * @example
 *   throw new AppError('Not found', { status: 404, meta: { id } })
 *   throw new AppError('Sign in to continue', { code: 'UNAUTHORIZED' }) // → 401
 *
 * @tags rule, error, error0
 * @related ErrorComponent, ErrorPageComponent, logger
 */
export const AppError = Error0.mark('AppError')
  // a string code that implies an HTTP status (map below)
  .use(
    codeStatusPlugin({
      codes: {
        UNAUTHORIZED: 401,
        FORBIDDEN: 403,
        UNSUBSCRIBED: 403,
      },
      transport: 'public',
    }),
  )
  // arbitrary structured metadata bag
  .use(metaPlugin())
  // carries the `.cause` chain across serialize/deserialize
  .use(causePlugin())
  // an HTTP `Response` built from the error
  .use(responsePlugin())
  // a redirect Point0 navigation short-circuits on
  .use(redirectPlugin())
  // "and don't try this again" — Point0's client stops query retries and reconnect cycles on it (public: the flag
  // exists for the client to act on)
  .use(preventRetryPlugin())
  // adapts Better Auth fetch errors — friendly message, marks them expected
  .use(betterAuthErrorPlugin)
  // unwraps a bare `new Error()` cause — hoists its message/stack/cause onto this one
  .use(flatOriginalPlugin())
  // whether to report to Sentry (public: the client decides too)
  .use(
    expectedPlugin({
      transport: 'public',
      override: (error) => {
        const code = (error as { code?: string }).code
        // Point0's unmatched-route 404 (POINT0_NOT_FOUND — bots, scanners, stale chunk URLs) is expected → out of
        // Sentry; NO_OUTPUT and every 5xx still report.
        if (code === POINT0_ERROR_CODES_MAP.NOT_FOUND) {
          return true
        }
      },
    }),
  )
  // the error's own log severity; the logger honors it over the call site (most-dangerous first; public)
  .use(levelPlugin({ levels: ['fatal', 'error', 'warn', 'info', 'debug', 'trace'], transport: 'public' }))
  // gates the stack (private by default)
  .use(stackPlugin())

export type AppError = InstanceType<typeof AppError>
