import { root } from '@/lib/root'
import { authorizedOnlyPlugin } from '@/modules/auth/plugins'
import { coreRequest } from '@/modules/core/client'
import type { NetworkView } from '@/features/network/shared'
import { z } from 'zod'

export const networkQuery = root.lets
  .query()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    return { network: await coreRequest<NetworkView>('/network') }
  })
  .query()

export const networkUpdateMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(z.object({ lan_interface: z.string().min(1).nullable() }))
  .loader(async ({ input }) => {
    return { network: await coreRequest<NetworkView>('/network', { method: 'PUT', body: input }) }
  })
  .mutation()
