import { engine } from '@/engine'
import { onShutdown } from '@/lib/shutdown'
import { createInitialAdmin } from '@/features/admin/init'
import { startWorkers } from '@/modules/worker'

onShutdown('engine', ['prisma'], async () => await engine.dispose())

// Serve, seed the admin, and start the background workers concurrently for a faster startup. No try/catch on purpose — a
// failure rejects this top-level await and lib/shutdown's unhandledRejection handler runs the graceful shutdown.
await Promise.all([engine.serve(), createInitialAdmin(), startWorkers()])
