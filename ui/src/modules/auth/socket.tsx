import { appChannel } from '@/modules/socket/channel'
import { queryClient } from '@/lib/query-client'
import { getMeQuery } from '@/modules/auth/api'
import { reconnectAll } from '@point0/core/socket'
import { useEffect, useRef } from 'react'
import { toast } from 'sonner'
import { z } from 'zod'

/**
 * Auth over the socket — the server tells the affected tabs that a session or a user is no longer valid.
 *
 * The flow: better-auth deletes a session row (a sign-out anywhere, an admin revoke, a ban — every path funnels through
 * the `session.delete` database hook in `server.ts`) → the hook pushes the event into the personal room (`sessionSpace`
 * / `userSpace`) and `refresh`es the same room — the connector re-runs against the dead session and the identity flips
 * to guest. Everything rides the rooms (exact topics): enrollment is a guarantee, so a session's/user's room holds
 * exactly their live connections — one room is the address for pushes and admin commands alike, no identity scan.
 */

/**
 * Every signed-in connection's personal room, filled by the server itself (no client join) — THE address for per-user
 * pushes: grow a `clientHandler` from this space and `sendToClient(payload, { room: { userId } })` reaches every device
 * of the user. `userBannedHandler` below rides it; guests hold no room.
 *
 * @tags socket, space
 * @related appChannel, sessionSpace, userBannedHandler
 */
export const userSpace = appChannel.lets
  .space<{ userId: string }>()
  .enroller(({ identity }) => (identity.userId === null ? undefined : { userId: identity.userId }))
  .space()

/**
 * The session twin of `userSpace`: one room per better-auth session — the address for "this session only" pushes (every
 * tab riding the same cookie, not the user's other devices). `sessionEndedHandler` below rides it.
 *
 * @tags socket, space
 * @related appChannel, userSpace, sessionEndedHandler
 */
export const sessionSpace = appChannel.lets
  .space<{ sessionId: string }>()
  .enroller(({ identity }) => (identity.sessionId === null ? undefined : { sessionId: identity.sessionId }))
  .space()

/**
 * "Your session ended" — a sign-out in another tab of this session, or an admin revoke. Pushed into the session's
 * `sessionSpace` room; the push itself is the whole payload, and by the time it arrives the server has already
 * refreshed the connection to guest.
 *
 * @tags socket, auth
 * @related AuthSocketSync, sessionSpace
 */
export const sessionEndedHandler = sessionSpace.lets.clientHandler().clientHandler()

/**
 * "You are banned" — pushed into the user's `userSpace` room before their sessions are revoked, so every device learns
 * WHY, not just that it signed out.
 *
 * @tags socket, auth
 * @related AuthSocketSync, userSpace
 */
export const userBannedHandler = userSpace.lets
  .clientHandler()
  .serverSend(z.object({ reason: z.string().nullable(), expiresAt: z.date().nullable() }))
  .clientHandler()

/**
 * Keeps this tab's socket and auth state in sync. Two directions:
 *
 * - Server → client: the `sessionEnded` / `userBanned` pushes drop the signed-in caches — every tab of the session/user
 *   flips to guest, not only the tab that acted (the server has already refreshed the connection itself). The bare
 *   hooks ride the connection's enrolled rooms; a guest holds none, so they idle until a sign-in enrolls one.
 * - Client → server: when `me` flips INTO a signed-in user (this tab's sign-in `refetchQuery`, an impersonation's cache
 *   reset), reconnect the socket so the connector re-runs with the fresh cookie.
 *
 * Mounted once in `app.client.tsx`, inside `<appChannel.Connection>`.
 *
 * @tags socket, auth
 * @related sessionEndedHandler, userBannedHandler, appChannel
 */
export const AuthSocketSync = (): null => {
  // subscribe without fetching — whoever renders `me` keeps it fresh
  const meData = getMeQuery.useQuery(undefined, { enabled: false }).data
  const userId = meData?.me?.user.id ?? null

  sessionEndedHandler.useOnMessageFromServer(() => {
    void queryClient.resetQueries()
  })
  userBannedHandler.useOnMessageFromServer(({ message }) => {
    toast.error(message.reason ? `You are banned: ${message.reason}` : 'You are banned')
    void queryClient.resetQueries()
  })

  // `undefined` = no `me` knowledge seen yet — the FIRST knowledge is not a transition (the socket connected with the
  // same cookies that `me` was read with)
  const lastKnownUserId = useRef<string | null | undefined>(undefined)
  useEffect(() => {
    if (!meData) {
      return // a knowledge gap (`queryClient.clear()`), not a transition — wait for the next `me`
    }
    const prev = lastKnownUserId.current
    lastKnownUserId.current = userId
    if (prev === undefined || prev === userId) {
      return // not a transition
    }
    if (userId === null) {
      // signing OUT needs no client reconnect: every path into `me: null` goes through a server-side session death,
      // and its hook has already `refresh`ed this connection to guest — in place, without dropping the socket.
      // A `reconnectAll()` here would tear the socket down a second time for nothing.
      return
    }
    reconnectAll()
  }, [meData, userId])

  return null
}
