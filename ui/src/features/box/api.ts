import { root } from '@/lib/root'
import { authorizedOnlyPlugin } from '@/modules/auth/plugins'
import { coreRequest } from '@/modules/core/client'

/** core/vibedpn/api/app.py Health: the role is what the panel builds its menu by. */
type Health = { status: 'ok'; version: string; role: string | null }

export const boxRoleQuery = root.lets
  .query()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    return { role: (await coreRequest<Health>('/health')).role }
  })
  // the role changes only with a new vibedpn init, which restarts the panel too
  .query({ staleTime: Infinity })
