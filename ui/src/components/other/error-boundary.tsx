import * as React from 'react'

import { Button } from '@/components/ui/button'
import { ErrorComponent } from '@/components/other/error'
import { logger } from '@/lib/logger'
import { cn } from '@/utils'

const l = logger.child('error-boundary')

// A code-split page chunk whose hashed URL 404s after a redeploy: an open tab still holds the old index and imports a
// filename that no longer exists. The fix is a single automatic reload — it pulls the fresh index and the new chunk
// names — not an error page and not a Sentry report, since this is an expected outcome of shipping, not a bug. Browsers
// phrase the failure differently, so match all three, and walk the cause chain (Point0 wraps the raw TypeError).
const STALE_CHUNK_RELOAD_AT_KEY = 'point0:stale-chunk-reload-at'
const STALE_CHUNK_RELOAD_COOLDOWN_MS = 10_000
const STALE_CHUNK_MESSAGE =
  /failed to fetch dynamically imported module|error loading dynamically imported module|importing a module script failed/i

const isStaleChunkError = (error: unknown): boolean => {
  for (let current: unknown = error, depth = 0; current instanceof Error && depth < 5; depth += 1) {
    if (STALE_CHUNK_MESSAGE.test(current.message)) {
      return true
    }
    current = (current as { cause?: unknown }).cause
  }
  return false
}

type ErrorBoundaryFallbackProps = {
  error: Error
  reset: () => void
}

type ErrorBoundaryProps = {
  children: React.ReactNode
  className?: string
  onError?: (error: Error, errorInfo: React.ErrorInfo) => void
  fallback?: (props: ErrorBoundaryFallbackProps) => React.ReactNode
}

type ErrorBoundaryState = {
  error: Error | null
}

export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  override state: ErrorBoundaryState = { error: null }
  private hmrDispose?: () => void

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  override componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    // Runs in the commit phase, before the browser paints, so the reload happens without the error UI flashing.
    if (this.reloadIfStaleChunk(error)) {
      return
    }
    this.props.onError?.(error, errorInfo)
    l.error(error, { componentStack: errorInfo.componentStack })
  }

  /**
   * Reload once on a stale-chunk error and report nothing. The `sessionStorage` stamp breaks a reload loop: if the
   * chunk is genuinely gone (a broken deploy/CDN, not just a stale tab), the second failure within the cooldown falls
   * through to the normal error UI and Sentry report instead of reloading forever.
   */
  private reloadIfStaleChunk(error: Error): boolean {
    if (!isStaleChunkError(error)) {
      return false
    }
    const lastReloadAt = Number(sessionStorage.getItem(STALE_CHUNK_RELOAD_AT_KEY) ?? 0)
    if (Date.now() - lastReloadAt < STALE_CHUNK_RELOAD_COOLDOWN_MS) {
      return false
    }
    sessionStorage.setItem(STALE_CHUNK_RELOAD_AT_KEY, String(Date.now()))
    window.location.reload()
    return true
  }

  override componentDidMount() {
    try {
      // eslint-disable-next-line @typescript-eslint/no-unnecessary-condition
      if (import.meta.hot) {
        const handler = () => this.reset()
        import.meta.hot.on('vite:beforeUpdate', handler)
        this.hmrDispose = () => import.meta.hot.off('vite:beforeUpdate', handler)
      }
    } catch {
      // ignore in case if it is not vite, but bun
    }
  }

  override componentWillUnmount() {
    this.hmrDispose?.()
  }

  reset = () => {
    this.setState({ error: null })
  }

  override render(): React.ReactNode {
    const { error } = this.state
    const { children, className, fallback } = this.props

    if (!error) {
      return children
    }

    if (fallback) {
      return fallback({ error, reset: this.reset })
    }

    return (
      <div className={cn('flex min-h-screen w-full items-center justify-center bg-background p-7', className)}>
        <ErrorComponent
          error={error}
          className="max-w-3xl"
          content={
            <div className="flex gap-buttons-gap-sm">
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  this.reset()
                }}
              >
                Try again
              </Button>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => {
                  window.location.reload()
                }}
              >
                Reload
              </Button>
            </div>
          }
        />
      </div>
    )
  }
}
