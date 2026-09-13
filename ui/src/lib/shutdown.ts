// Graceful shutdown for the long-lived server process.
//
// Prisma, pg-boss, and the HTTP engine hold open sockets, in-flight transactions, and pending jobs. If the process
// just exited, those would be severed mid-flight — dropped connections, half-finished work, jobs stuck "active". So
// every such resource registers an `onShutdown(...)` cleanup, and when the process is asked to stop we run them all
// (in parallel — but a callback tears down before the deps it declares, so a dependency outlives what uses it —
// bounded by a 30s timeout) before exiting. So pg-boss stops and drains its jobs before Prisma closes the connection
// those jobs use. `shutdown()` is the single, idempotent exit path —
// termination signals and fatal top-level errors both funnel into it.

import { logger } from '@/lib/logger'
import '@point0/core/server-only'

const l = logger.child('shutdown')

type ShutdownCallbackFn = () => Promise<unknown> | unknown
type NormalizedShutdownCallbackFn = () => Promise<unknown>
type ShutdownCallbackRecord = { target: string; deps: string[]; fn: NormalizedShutdownCallbackFn }

const shutdownTimeoutMs = 30000
const callbacks: ShutdownCallbackRecord[] = []
// The catchable "please stop" signals we handle, each mapped to the exit code we report after cleanup.
//
// Why only these three: they're the realistic ways a process is *asked* to terminate and can still react. The hard
// kills — SIGKILL and SIGSTOP — are uncatchable by design (the kernel acts at once), so there's nothing to handle and
// no chance to clean up; they're the escape hatch an orchestrator uses if we ever hang past its grace period. SIGQUIT
// (core-dump on Ctrl+\) and the SIGUSR* signals aren't part of a normal stop, so we leave them alone.
//
// Exit codes follow the Unix "128 + signal number" convention — except SIGTERM. A process killed by signal N exits
// 128+N (SIGINT=2 → 130, SIGHUP=1 → 129). SIGTERM (15) would be 143, but we deliberately map it to 0: SIGTERM is how
// orchestrators (Docker / Kubernetes / Railway / systemd, or a plain `kill <pid>`) ask for a *graceful* stop on a
// deploy or scale-down, so a clean shutdown there is a success, not a crash.
const signalExitCodes: Partial<Record<NodeJS.Signals, number>> = {
  SIGINT: 130, // Ctrl+C in an interactive terminal — a human stopping the process by hand
  SIGTERM: 0, // default `kill` / orchestrator "stop gracefully" — expected, so report success
  SIGHUP: 129, // the controlling terminal or SSH session closed (the classic "hang up")
}

/**
 * Register a callback that runs once during graceful shutdown.
 *
 * Callbacks run in parallel under a combined 30s budget. Pass `deps` — the other `target`s this one depends on — to
 * force ordering: this callback tears down _before_ every dep it names, so a dependency outlives what uses it (start
 * order, reversed). Deps that aren't registered are ignored (we don't check they exist), so naming one absent from this
 * entrypoint is harmless. `target` is logged and used in error messages — keep it short (e.g. `'pgboss'`, `'prisma'`).
 *
 * @example
 *   onShutdown('prisma', async () => await prisma.$disconnect()) // depends on nothing → torn down last
 *   onShutdown('pgboss', ['prisma'], async () => await boss.stop()) // needs prisma → stops before prisma disconnects
 *
 * @tags shutdown
 */
export function onShutdown(target: string, callback: ShutdownCallbackFn): void
export function onShutdown(target: string, deps: string[], callback: ShutdownCallbackFn): void
export function onShutdown(
  target: string,
  depsOrCallback: string[] | ShutdownCallbackFn,
  callback?: ShutdownCallbackFn,
): void {
  const deps = Array.isArray(depsOrCallback) ? depsOrCallback : []
  const fn = (Array.isArray(depsOrCallback) ? callback : depsOrCallback) as ShutdownCallbackFn
  callbacks.push({ target, deps, fn: async () => await fn() })
}

// Run one callback with timing + logging. Never throws — a failed teardown is logged and shutdown moves on.
const runCallback = async (callback: ShutdownCallbackRecord) => {
  const startTime = performance.now()
  try {
    l.info(`Start shutting down ${callback.target}...`)
    const output = await callback.fn()
    l.info(`Successfully shut down ${callback.target}`, { durationMs: performance.now() - startTime, output })
  } catch (error) {
    l.error(`Failed to shut down ${callback.target}`, { error, durationMs: performance.now() - startTime })
  }
}

let isShuttingDown = false

/**
 * Run every registered shutdown callback — in parallel, but each tears down before the `deps` it declared via
 * `onShutdown` (30s budget) — then exit. Idempotent — the first call wins; a repeated signal is a no-op. `exitCode`
 * defaults to the current `process.exitCode` (or 1); the signal handlers pass the matching code (SIGTERM → 0, ... ).
 *
 * @tags shutdown
 */
export const shutdown = async (exitCode: typeof process.exitCode = process.exitCode ?? 1) => {
  if (isShuttingDown) {
    return
  }

  isShuttingDown = true

  try {
    l.info('Start shutting down...')

    // If a cleanup callback hangs (a socket that won't close, a stuck query), don't block exit forever — race the
    // whole batch against a timeout and force-exit once it elapses.
    let timeout: Timer | undefined
    const timeoutPromise = new Promise<void>((resolve) => {
      timeout = setTimeout(() => {
        l.warn(`Graceful shutdown timed out after ${shutdownTimeoutMs}ms`)
        resolve()
      }, shutdownTimeoutMs)
    })

    // Dependency-ordered parallel teardown: every callback gets a gate. A callback runs once everything that depends on
    // its `target` has finished — i.e. it tears down *before* the things it depends on, so a dependency outlives what
    // uses it. Independent callbacks overlap; deps naming an unregistered target match nothing; a cycle never resolves
    // and falls through to the timeout above.
    const gates = new Map(callbacks.map((callback) => [callback, Promise.withResolvers<void>()] as const))
    const runAll = [...gates].map(async ([callback, gate]) => {
      // Let every callback that depends on this one (its dependents) tear down first.
      const dependents: Promise<void>[] = []
      for (const [other, otherGate] of gates) {
        if (other !== callback && other.deps.includes(callback.target)) {
          dependents.push(otherGate.promise)
        }
      }
      await Promise.all(dependents)
      await runCallback(callback)
      gate.resolve()
    })

    await Promise.race([Promise.all(runAll), timeoutPromise])

    if (timeout) {
      clearTimeout(timeout)
    }
    l.info('Successfully shut down')
    process.exit(exitCode ?? 1)
  } catch (error) {
    l.error('Failed to shut down', error)
    process.exit(1)
  }
}

// Catch termination signals with plain `process.on` listeners — NOT `signal-exit`. Under Bun, signal-exit fires its
// handler but does not actually hold the process open for async work: it terminates anyway and cuts the callbacks off
// (verified). A `process.on(signal)` listener that stays installed does stop Bun's default termination, so the async
// cleanup runs to completion before we exit ourselves. The `isShuttingDown` guard makes a repeated signal a no-op.
const terminationSignals: NodeJS.Signals[] = ['SIGINT', 'SIGTERM', 'SIGHUP']
for (const signal of terminationSignals) {
  process.on(signal, () => {
    l.info(`Received ${signal}`)
    void shutdown(signalExitCodes[signal] ?? 1)
  })
}

// A fatal error nothing caught means the process is in an unknown state — clean up and exit non-zero rather than limp
// on with half-broken services. `once`, not `on`: we only need to *start* shutdown once (the `isShuttingDown` guard
// handles the rest), and a second fault mid-teardown should crash hard, not loop back here.
process.once('uncaughtException', (error) => {
  l.error('Uncaught exception, shutting down gracefully', error)
  void shutdown(1)
})

process.once('unhandledRejection', (reason) => {
  l.error('Unhandled rejection, shutting down gracefully', reason)
  void shutdown(1)
})
