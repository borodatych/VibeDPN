import { root } from '@/lib/root'
import { serverEnv } from '@/modules/env/server'
import '@point0/core/server-only'

export const apiHealthAction = root.lets.action('GET', '/api/health').action(async () => {
  return new Response('OK', {
    status: 200,
    headers: {
      'content-type': 'text/plain; charset=utf-8',
      // The live deploy's release (SOURCE_VERSION), so an external check can read which release is serving. `unknown`
      // keeps the header always present (SOURCE_VERSION is empty only in local).
      'x-release': serverEnv.SOURCE_VERSION || 'unknown',
    },
  })
})

export type HealthCheck = { ok: boolean; status: number; durationMs: number }

export const isApiHealthyDetailed = async (): Promise<HealthCheck> => {
  const start = performance.now()
  try {
    const response = await fetch(serverEnv.SERVER_URL + apiHealthAction.route.get())
    // Drain the body even though we only need the status: Bun keeps fetch connections alive, and an unconsumed response
    // pins its socket + native buffers until GC — a slow RSS leak on a per-minute heartbeat.
    await response.text()
    return { ok: response.ok, status: response.status, durationMs: performance.now() - start }
  } catch {
    return { ok: false, status: 0, durationMs: performance.now() - start }
  }
}

export const isApiHealthy = async () => (await isApiHealthyDetailed()).ok

export const waitForApiToBeHealthy = async ({
  interval = 100,
  timeout = 10000,
}: { interval?: number; timeout?: number } = {}) => {
  const startTime = Date.now()
  while (!(await isApiHealthy())) {
    await new Promise((resolve) => setTimeout(resolve, interval))
    if (Date.now() - startTime > timeout) {
      throw new Error('API is not healthy after timeout')
    }
  }
}

export const isClientHealthyDetailed = async (): Promise<HealthCheck> => {
  const start = performance.now()
  try {
    const response = await fetch(serverEnv.CLIENT_URL)
    const text = await response.text()
    return { ok: text.includes('</html>'), status: response.status, durationMs: performance.now() - start }
  } catch {
    return { ok: false, status: 0, durationMs: performance.now() - start }
  }
}

export const isClientHealthy = async () => (await isClientHealthyDetailed()).ok

export const waitForClientToBeHealthy = async ({
  interval = 100,
  timeout = 10000,
}: { interval?: number; timeout?: number } = {}) => {
  const startTime = Date.now()
  while (!(await isClientHealthy())) {
    await new Promise((resolve) => setTimeout(resolve, interval))
    if (Date.now() - startTime > timeout) {
      throw new Error('Client is not healthy after timeout')
    }
  }
}
