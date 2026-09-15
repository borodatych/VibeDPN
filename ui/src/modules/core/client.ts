import { AppError } from '@/lib/error'
import { CORE_API_HOST } from '@/modules/core/proxy'
import { serverEnv } from '@/modules/env/server'
import '@point0/core/server-only'

const CORE_TIMEOUT_MS = 10_000

/** What core answered: its body, or its status with the `detail` it gives for an error. */
export type CoreAnswer<T> = { ok: true; body: T } | { ok: false; status: number; detail: string }

type CoreInit = { method: 'PUT'; body: unknown } | { method: 'DELETE' }

/**
 * A JSON request to the core API from a server loader, without throwing on core's own refusals: a loader that has a
 * meaning for 404 or 503 (no node on this box, the node does not answer) decides itself. Core not answering at all is
 * still an `AppError` 502.
 *
 * @tags core
 * @related coreRequest, coreApiProxy
 */
export const coreFetch = async <T>(path: string, init?: CoreInit): Promise<CoreAnswer<T>> => {
  let response: Response
  try {
    response = await fetch(`http://${CORE_API_HOST}:${serverEnv.CORE_API_PORT}${path}`, {
      method: init?.method ?? 'GET',
      headers: init && 'body' in init ? { 'Content-Type': 'application/json' } : undefined,
      body: init && 'body' in init ? JSON.stringify(init.body) : undefined,
      signal: AbortSignal.timeout(CORE_TIMEOUT_MS),
    })
  } catch {
    throw new AppError('The core of the box does not answer', { status: 502 })
  }
  // 204 of a DELETE has no body
  const body: unknown = response.status === 204 ? null : await response.json().catch(() => null)
  if (response.ok) {
    return { ok: true, body: body as T }
  }
  const detail =
    body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string'
      ? body.detail
      : `Core answered HTTP ${response.status}`
  return { ok: false, status: response.status, detail }
}

/**
 * A JSON request to the core API from a server loader of the panel. Core answers errors with `{ detail }`; they come
 * back as `AppError` with core's status, so a refused mode change shows core's own reason.
 *
 * @tags core
 * @related coreFetch, coreApiProxy
 */
export const coreRequest = async <T>(path: string, init?: CoreInit): Promise<T> => {
  const answer = await coreFetch<T>(path, init)
  if (!answer.ok) {
    throw new AppError(answer.detail, { status: answer.status })
  }
  return answer.body
}
