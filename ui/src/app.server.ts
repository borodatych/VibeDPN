import { engine } from '@/engine'
import { onShutdown } from '@/lib/shutdown'
import { createInitialAdmin } from '@/features/admin/init'

onShutdown('engine', ['prisma'], async () => await engine.dispose())

// Serve, seed the admin, and start the background workers concurrently for a faster startup. No try/catch on purpose — a
// failure rejects this top-level await and lib/shutdown's unhandledRejection handler runs the graceful shutdown.
// `lite` runs no background workers: pg-boss and its connections are not even in the bundle.
const startWorkers = async () => {
  // eslint-disable-next-line no-restricted-properties -- UI_VARIANT is a build-time constant (engine.ts), not runtime env
  if (process.env.UI_VARIANT === 'full') {
    const { startWorkers: start } = await import('@/modules/worker')
    await start()
  }
}
await Promise.all([engine.serve(), createInitialAdmin(), startWorkers()])
