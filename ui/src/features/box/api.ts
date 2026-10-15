import { root } from '@/lib/root'
import { authorizedOnlyPlugin } from '@/modules/auth/plugins'
import { coreRequest } from '@/modules/core/client'

// The menu notices a client switched on or off after this long.
const BOX_REFRESH_MS = 30_000

/** core/vibedpn/api/app.py Health: the role and whether the torrent client is on are what the panel builds its menu by. */
type Health = { status: 'ok'; version: string; role: string | null; torrents: boolean }

export const boxRoleQuery = root.lets
  .query()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    const health = await coreRequest<Health>('/health')
    return { role: health.role, torrents: health.torrents }
  })
  // the role changes only with a new vibedpn init, which restarts the panel too; the client is switched on and off
  // by the owner at any time, and the menu follows within the interval
  .query({ refetchInterval: BOX_REFRESH_MS })
