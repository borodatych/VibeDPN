import type { AppError } from '@/lib/error'
import { serverEnv } from '@/modules/env/server'
import { type MiddlewareFn } from '@point0/core'
import '@point0/core/server-only'
import { Axiom } from '@axiomhq/js'
import type { LogRecord, Sink } from '@logtape/logtape'

// One nullable handle: non-null exactly when Axiom is live — `HOST_ENV != local` and every piece configured. Every entry
// point gates on it, so there are no env non-null assertions and the datasets are plain strings once we're past the gate.
// Built lazily by `initAxiom`, never at import time: `lib/logger.ts` imports this module for the sink, and the logger is
// imported almost everywhere — so importing it must not read env or open a client a script/test/tool never asked for.
let axiom: { client: Axiom; logsDataset: string; metricsDataset: string } | null = null

/**
 * Initialize server Axiom and register its shutdown flush. Call once at startup (`index.server.ts`), after the server
 * env is validated. Off in local, or when any var is missing — then `axiom` stays `null` and the sink, `axiomMetric`,
 * and the middleware all no-op. Mirrors `initSentryServer` / `initMixpanelServer`. Nothing here runs at import time.
 *
 * @tags axiom
 * @related axiomGetSink, axiomMetric, axiomMetricsMiddleware
 */
export const initAxiom = async (): Promise<void> => {
  const { HOST_ENV, AXIOM_TOKEN: token, AXIOM_EDGE: edge } = serverEnv
  // Off in local (never ship local-dev data to the real datasets), or when any piece is missing.
  if (HOST_ENV === 'local' || !token || !edge) {
    return
  }
  // `edge` (the region's ingest domain) routes ingest to the datasets' region; `url` would use the legacy path and 404
  // against an edge host. The batching client buffers events and flushes every ~1s on its own timer (and on shutdown).
  const client = new Axiom({ token, edge })
  // Fixed dataset names — the token is scoped to one org, so `logs` / `metrics` are unambiguous (provisioned by `provision.ts`).
  axiom = { client, logsDataset: 'logs', metricsDataset: 'metrics' }
  // Flush the buffer on shutdown, registered from inside the module. Dynamic import on purpose: a static `onShutdown`
  // import would form a `logger → axiom → shutdown → logger` cycle (both ends use the binding at module-eval time).
  const { onShutdown } = await import('@/lib/shutdown')
  onShutdown('axiom', async () => await client.flush())
}

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

// `environment` (HOST_ENV) + `release` (SOURCE_VERSION) — the deploy labels stamped top-level on every Axiom event,
// logs and metrics alike, so both datasets filter directly by stage/deploy. `release` is dropped when SOURCE_VERSION is
// empty (local).
const deployFields = (): Record<string, string> => ({
  environment: serverEnv.HOST_ENV,
  ...(serverEnv.SOURCE_VERSION ? { release: serverEnv.SOURCE_VERSION } : {}),
})

/**
 * LogTape sink that ships every record to the Axiom logs dataset as-is — Axiom is the log store. Wired in
 * `lib/logger.ts` next to `console`/`sentry`, server side only, so every `logger.*` is mirrored with no extra call
 * sites. No-op until `initAxiom` runs / when disabled. Never throws (logging must not crash on Axiom).
 *
 * @tags axiom, logger
 * @related initAxiom, logger, sentryGetSink
 */
export const axiomGetSink = (): Sink => {
  return (record: LogRecord) => {
    if (!axiom) {
      return
    }
    try {
      // The logger already normalized every prop and serialized errors into flat, JSON-safe fields
      // (name/message/stack/code/...), so props go in as-is. The one exception: it re-adds the LIVE `Error` instance under
      // `error` for the Sentry sink — drop it here, since it JSON-encodes to `{}` and only duplicates those flat fields.
      //
      // All props go under one `props` field, NOT flattened to the top level. Axiom caps a dataset at 256 top-level
      // fields and REJECTS any event that would add one past the cap, and log props are unbounded (every new key sticks
      // in the schema forever). `props` is configured as an Axiom map field (see README), so its keys live as map entries
      // — queried via `props["request.pathname"]` in APL — and never grow the field count.
      const props = { ...record.properties }
      delete props.error
      axiom.client.ingest(axiom.logsDataset, [
        {
          _time: new Date(record.timestamp).toISOString(),
          level: record.level,
          category: record.category.join(':'),
          message: messageToString(record.message),
          ...deployFields(),
          props,
        },
      ])
    } catch {
      // never let logging crash because of Axiom
    }
  }
}

/**
 * Record one metric data point to the Axiom metrics dataset — call it from anywhere on the server. A metric is just an
 * event (`{ metric: <name>, environment, release, ...fields }`) aggregated later in APL (count / avg / percentiles), so
 * there is no instrument to declare up front: to add a new metric, just call this with a new name and whatever fields
 * make sense. No-op when Axiom is disabled.
 *
 * @example
 *   axiomMetric('cache.miss', { key })
 *   axiomMetric('email.sent', { template: 'welcome' })
 *
 * @tags axiom, metrics
 * @related axiomMetricsMiddleware
 */
export const axiomMetric = (name: string, fields?: Record<string, unknown>): void => {
  if (!axiom) {
    return
  }
  axiom.client.ingest(axiom.metricsDataset, [
    {
      metric: name,
      ...deployFields(),
      ...fields,
    },
  ])
}

/**
 * Point0 middleware that records a per-request `request` metric — duration plus `variant` / `status` / `method` /
 * `point` / `renders` tags. A bare `MiddlewareFn` attached with `.middleware()` (not `.use()`) so the compiler strips
 * this server-only code from the client bundle; put it outermost on the root so it times the whole request. No-op when
 * Axiom is disabled, and recording can never break a request.
 *
 * @tags axiom, metrics, point0
 * @related axiomMetric, root
 */
export const axiomMetricsMiddleware: MiddlewareFn<AppError> = async ({ next, request }) => {
  const start = performance.now()
  let result: Awaited<ReturnType<typeof next>> | undefined
  try {
    result = await next()
    return result
  } finally {
    try {
      // Skip internal server-to-server fetches — only real inbound requests are metered.
      if (!request.from.server) {
        axiomMetric('request', {
          side: 'server',
          method: request.method,
          variant: result?.variant.type ?? 'crash',
          ...(result ? { status: result.response.status } : {}),
          ...('point' in request.variant ? { point: request.variant.point?.id ?? 'unknown' } : {}),
          durationMs: performance.now() - start,
          // `request.renders` is the SSR render-pass count — 0 for non-page requests, so only record real renders.
          ...(request.renders ? { renders: request.renders } : {}),
        })
      }
    } catch {
      // metrics must never break a request
    }
  }
}
