import { queryClient } from '@/lib/query-client'
import type { authServer } from '@/modules/auth/server'
import { clientEnv } from '@/modules/env/client'
import { env } from '@point0/core'
import { adminClient, inferAdditionalFields } from 'better-auth/client/plugins'
import { createAuthClient } from 'better-auth/react'

/**
 * Configured better-auth React client.
 *
 * Use for browser-side mutations (sign in, sign out, link account, change password, ...). For reading the current
 * session prefer `getMeQuery` from `api.ts` — `authClient` is reserved for mutations so that all session reads can be
 * cached uniformly.
 *
 * Throws if called from server code. But allowed to import on server code.
 *
 * @tags auth, client
 * @related getMeQuery, authServer
 */
export const authClient = env.side.define({
  client: createAuthClient({
    baseURL: clientEnv.SERVER_URL,
    fetchOptions: {
      credentials: 'include',
      throw: true,
      onRequest: (request) => {
        return request
      },
    },
    plugins: [adminClient(), inferAdditionalFields<typeof authServer>()],
  }),
  server: new Proxy(
    {},
    {
      get() {
        // You can import, but lets use it only like mutations, not queries, so never on server
        throw new Error('Do not use authClient on the server')
      },
    },
  ) as never,
})

export const signOut = ({
  onError,
  onSettled,
  onSuccess,
}: { onError?: (error: unknown) => void; onSettled?: () => void; onSuccess?: () => void } = {}) => {
  void (async () => {
    try {
      await authClient.signOut()
      onSuccess?.()
    } catch (error) {
      onError?.(error)
    } finally {
      queryClient.clear()
      onSettled?.()
    }
  })()
}
