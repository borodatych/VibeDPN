import { root } from '@/lib/root'
import { authorizedOnlyPlugin } from '@/modules/auth/plugins'
import { coreFetch, coreRequest } from '@/modules/core/client'
import type { BoxStatus, DpnCountry, RoutingView } from '@/features/status/shared'
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

export const vpsLanAccessMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(z.object({ allowed: z.boolean() }))
  .loader(async ({ input }) => {
    return { access: await coreRequest<{ allowed: boolean }>('/uplinks/vps/lan-access', { method: 'PUT', body: input }) }
  })
  .mutation()

// Proposals of the whole network change slowly; the list is asked when the card opens.
const COUNTRIES_STALE_MS = 5 * 60_000

export const dpnCountriesQuery = root.lets
  .query()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    const answer = await coreFetch<DpnCountry[]>('/dpn/countries')
    return answer.ok ? { countries: answer.body, reason: null } : { countries: [], reason: answer.detail }
  })
  .query({ staleTime: COUNTRIES_STALE_MS })

export const dpnCountryMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(z.object({ country: z.string().length(2).nullable() }))
  .loader(async ({ input }) => {
    return { dpn: await coreRequest<{ country: string | null }>('/dpn/country', { method: 'PUT', body: input }) }
  })
  .mutation()
