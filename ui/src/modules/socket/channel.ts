import { root } from '@/lib/root'
import { getMe } from '@/modules/auth/server'

/**
 * The app-wide socket channel. Deliberately open — anonymous visitors connect too: the identity is `{ userId, sessionId
 * }`, both `null` for everyone signed out. A handler that must not reach anonymous connections grows from a space whose
 * enroller skips guests (`userSpace` / `sessionSpace` in `modules/auth/socket.tsx`), or targets `{ $identity: { userId:
 * { $ne: null } } }`.
 *
 * One `<appChannel.Connection>` in `app.client.tsx` holds the connection for the whole app. The connector captures the
 * identity at connect time; it changes only through a reconnect or a server `refresh` — the auth module owns both
 * directions (see `modules/auth/socket.tsx` and this module's README).
 *
 * @tags socket, channel
 * @related ideaCreatedHandler, AuthSocketSync
 */
export const appChannel = root.lets
  .channel()
  .connector(async ({ request }) => {
    const me = await getMe({ request })
    return me ? { userId: me.user.id, sessionId: me.session.id } : { userId: null, sessionId: null }
  })
  .channel()
