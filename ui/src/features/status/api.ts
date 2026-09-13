import { root } from '@/lib/root'
import { authorizedOnlyPlugin } from '@/modules/auth/plugins'
import { coreRequest } from '@/modules/core/client'
import type { BoxStatus, RoutingView } from '@/features/status/shared'
import { z } from 'zod'

// The uplink watchers of core probe every 5 s; polling faster shows nothing new.
const STATUS_REFRESH_MS = 5_000

export const boxStatusQuery = root.lets
  .query()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    return { status: await coreRequest<BoxStatus>('/status') }
  })
  .query({
    refetchInterval: STATUS_REFRESH_MS,
    staleTime: 0,
  })

export const routingUpdateMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(
    z.object({
      mode: z.enum(['off', 'full']).optional(),
      default_upstream: z.enum(['vps', 'dpn']).optional(),
    }),
  )
  .loader(async ({ input }) => {
    return { routing: await coreRequest<RoutingView>('/routing', { method: 'PUT', body: input }) }
  })
  .mutation()
