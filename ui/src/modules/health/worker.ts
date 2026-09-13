import { axiomMetric } from '@/modules/axiom'
import { serverEnv } from '@/modules/env/server'
import { isApiHealthyDetailed, isClientHealthyDetailed } from '@/modules/health/utils'
import { createWorker, every } from '@/modules/worker/utils'
import '@point0/core/server-only'

/**
 * Heartbeat, once a minute. Checks the API and client over the real public URL — exercising DNS/TLS/Railway-edge/app
 * end-to-end — and writes a `heartbeat` metric per `target`; when the beat stops, the Axiom "site down" monitor fires
 * on its absence. Also samples `process.memoryUsage()` into a `memory` metric, so RSS creep/spikes are queryable in
 * Axiom (`external`/`arrayBuffers` surface off-heap growth the JS heap hides).
 *
 * Off in local (no public URL, Axiom disabled) — on both knobs: `schedule.enabled` gates asking the database for the
 * cron, `work.enabled` gates executing jobs. Only gating the schedule left local executing a cron persisted by another
 * environment on the same database.
 *
 * @tags health, axiom, worker
 * @related axiomMetric, isApiHealthyDetailed, startHealthWorkers
 */
export const heartbeatWorker = createWorker(
  'heartbeat',
  async () => {
    const [api, client] = await Promise.all([isApiHealthyDetailed(), isClientHealthyDetailed()])
    axiomMetric('heartbeat', { target: 'api', ...api })
    axiomMetric('heartbeat', { target: 'client', ...client })
    const { rss, heapUsed, heapTotal, external, arrayBuffers } = process.memoryUsage()
    axiomMetric('memory', { rss, heapUsed, heapTotal, external, arrayBuffers })
    return { api: api.ok, client: client.ok }
  },
  {
    queue: { policy: 'exclusive', retryLimit: 0 },
    work: { enabled: serverEnv.HOST_ENV !== 'local' },
    schedule: { cron: every.minute, enabled: serverEnv.HOST_ENV !== 'local' },
  },
)

export const startHealthWorkers = async () => {
  await heartbeatWorker.start()
}
