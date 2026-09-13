import { AppError } from '@/lib/error'
import { sentryClientApi } from './client'
import { sentryServerApi } from './server'
import type { LogRecord, Sink } from '@logtape/logtape'
import { env } from '@point0/core'

export type SentryContext = Record<string, unknown>
export type SentryLevel = 'fatal' | 'error' | 'warning' | 'info'
export type SentryUser = { id?: string; email?: string; username?: string; impersonated?: string }

/**
 * Side-agnostic Sentry surface. `client.ts` and `server.ts` each implement it over their own SDK; `shared.ts` picks the
 * right one. When `enabled` is false (no DSN) every method is a no-op.
 *
 * @tags sentry
 */
export type SentryApi = {
  enabled: boolean
  captureException: (error: unknown, context?: { extra?: SentryContext }) => void
  captureMessage: (message: string, level?: SentryLevel) => void
  setUser: (user: SentryUser | null) => void
}

// The Point0 compiler replaces this `env.side.define` with just the current side's branch and prunes the other import,
// so the wrong-side SDK never reaches the bundle (see ./README.md → "How it works in code"). Init is side-specific and
// lives in `client.ts` / `server.ts` (`initSentryClient` / `initSentryServer`) — the entry points are already
// per-side, so there is no shared init.
const sentryApi: SentryApi = env.side.define({ client: sentryClientApi, server: sentryServerApi })

const messageToString = (parts: readonly unknown[]): string =>
  parts
    .map((part) => {
      if (typeof part === 'string') {
        return part
      }
      try {
        return JSON.stringify(part)
      } catch {
        return String(part)
      }
    })
    .join('')

/**
 * Report an error to Sentry from anywhere — server or browser. No-op when Sentry is disabled (no DSN) or the error is
 * `expected`. Most errors are captured automatically through the logger sink, so reach for this only for an explicit,
 * out-of-band report.
 *
 * @example
 *   sentryCaptureError(error, { orderId })
 *
 * @tags rule, sentry
 * @related logger, AppError, sentryGetSink
 */
export const sentryCaptureError = (error: unknown, context?: SentryContext): void => {
  // Expected errors (wrong password, etc.) are user-facing, not bugs — they stay in logs only. `AppError.isExpected`
  // normalizes any input, so we can pass it straight through.
  if (!sentryApi.enabled || AppError.isExpected(error)) {
    return
  }
  sentryApi.captureException(error, context ? { extra: context } : undefined)
}

/** Report a standalone message (no `Error` object) to Sentry. No-op when Sentry is disabled. */
export const sentryCaptureMessage = (message: string, level: SentryLevel = 'error'): void => {
  if (!sentryApi.enabled) {
    return
  }
  sentryApi.captureMessage(message, level)
}

/** Attach (or clear) the current user on Sentry events. No-op when Sentry is disabled. */
export const sentrySetUser = (user: SentryUser | null): void => {
  if (!sentryApi.enabled) {
    return
  }
  sentryApi.setUser(user)
}

/**
 * LogTape sink that forwards `error`/`fatal` records to Sentry, so every `logger.error`/`logger.fatal` — and therefore
 * `root.on('error')` and the client `ErrorBoundary`, which both funnel through the logger — is captured with no extra
 * call sites. Side-agnostic: it only calls `sentryCaptureError`, which dispatches to the current side's Sentry surface
 * and drops `expected` errors. Never throws (logging must not crash on Sentry).
 *
 * @tags sentry, logger
 * @related sentryCaptureError, logger
 */
export const sentryGetSink = (): Sink => {
  return (record: LogRecord) => {
    if (record.level !== 'error' && record.level !== 'fatal') {
      return
    }
    try {
      const { error, ...rest } = record.properties
      if (error instanceof Error) {
        sentryCaptureError(error, rest)
      } else {
        sentryCaptureMessage(messageToString(record.message), record.level)
      }
    } catch {
      // never let logging crash because of Sentry
    }
  }
}
