import { AppError } from '@/lib/error'
import { CORE_API_HOST } from '@/modules/core/proxy'
import { serverEnv } from '@/modules/env/server'
import '@point0/core/server-only'

const CORE_TIMEOUT_MS = 10_000

/**
 * A JSON request to the core API from a server loader of the panel. Core answers errors with `{ detail }`; they come back
 * as `AppError` with core's status, so a refused mode change shows core's own reason.
 *
 * @tags core
 * @related coreApiProxy
 */
export const coreRequest = async <T>(path: string, init?: { method: 'PUT'; body: unknown }): Promise<T> => {
  let response: Response
  try {
    response = await fetch(`http://${CORE_API_HOST}:${serverEnv.CORE_API_PORT}${path}`, {
      method: init?.method ?? 'GET',
      headers: init ? { 'Content-Type': 'application/json' } : undefined,
      body: init ? JSON.stringify(init.body) : undefined,
      signal: AbortSignal.timeout(CORE_TIMEOUT_MS),
    })
  } catch {
    throw new AppError('The core of the box does not answer', { status: 502 })
  }
  const body: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const detail =
      body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string'
        ? body.detail
        : `Core answered HTTP ${response.status}`
    throw new AppError(detail, { status: response.status })
  }
  return body as T
}
