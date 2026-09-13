import { startHealthWorkers } from '@/modules/health/worker'

/**
 * The worker assembly point: every background worker is registered here. Each module/feature exports a
 * `start<Module>Workers()` that starts its own workers; add it to this list. Called once from the server startup
 * pipeline. The position on workers + conventions live in the module README (`worker`).
 *
 * @id worker-index
 * @tags rule, worker
 * @related worker, createWorker, pgboss
 */
export const startWorkers = async () => {
  // here lets collect all workers from project
  await Promise.all([startHealthWorkers()])
}
