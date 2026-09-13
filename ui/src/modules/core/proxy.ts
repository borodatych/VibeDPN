import { getMe } from '@/modules/auth/server'
import { serverEnv } from '@/modules/env/server'
import type { Request0 } from '@point0/core/request0'
import '@point0/core/server-only'

/** Everything under this prefix goes to the core API; the rest of `/api/` belongs to the app itself. */
export const CORE_API_PREFIX = '/api/core'

/** Core listens on loopback only; the panel is on the host network next to it. */
export const CORE_API_HOST = '127.0.0.1'

// Hop-by-hop headers and the ones that describe the browser session, not the request to core.
const DROPPED_REQUEST_HEADERS = ['host', 'cookie', 'connection', 'keep-alive', 'transfer-encoding', 'upgrade']

/**
 * Forwards `/api/core/*` to the core API on loopback, only for a signed-in session. Core listens on 127.0.0.1 and has no
 * authentication of its own: this middleware is its only door from the LAN.
 *
 * @tags rule, auth, core
 */
export const coreApiProxy = async ({ request }: { request: Request0 }) => {
  if (!(await getMe({ request }))) {
    return Response.json({ message: 'Only for authorized users' }, { status: 401 })
  }
  const original = request.original
  const url = new URL(original.url)
  const target = new URL(
    `${url.pathname.slice(CORE_API_PREFIX.length) || '/'}${url.search}`,
    `http://${CORE_API_HOST}:${serverEnv.CORE_API_PORT}`,
  )
  const headers = new Headers(original.headers)
  for (const name of DROPPED_REQUEST_HEADERS) {
    headers.delete(name)
  }
  const hasBody = original.method !== 'GET' && original.method !== 'HEAD'
  try {
    return await fetch(target, {
      method: original.method,
      headers,
      body: hasBody ? await original.arrayBuffer() : undefined,
      redirect: 'manual',
    })
  } catch {
    return Response.json({ message: 'The core API does not answer' }, { status: 502 })
  }
}
