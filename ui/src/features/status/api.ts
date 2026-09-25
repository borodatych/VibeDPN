import { root } from '@/lib/root'
import { authorizedOnlyPlugin } from '@/modules/auth/plugins'
import { coreFetch, coreRequest } from '@/modules/core/client'
import type { BoxStatus, DpnCountry, DpnRegistration, RoutingView } from '@/features/status/shared'
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
      // an uplink key, not a fixed set: the names of the WireGuard exits are the owner's
      default_upstream: z.string().optional(),
      // routing.fallback as a whole, in order; [] empties it
      fallback: z.array(z.string()).optional(),
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
    return {
      access: await coreRequest<{ allowed: boolean }>('/uplinks/vps/lan-access', { method: 'PUT', body: input }),
    }
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

/** What registering the consumer identity would cost: asking spends nothing (decision 4). */
export const dpnRegistrationQuery = root.lets
  .query()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    const answer = await coreFetch<DpnRegistration>('/dpn/registration')
    return answer.ok ? { registration: answer.body, reason: null } : { registration: null, reason: answer.detail }
  })
  .query({ staleTime: 0 })

/** The registration itself: a transaction on the network, started only by the owner's click. */
export const dpnRegisterMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    const done = await coreRequest<{ result: string; status: string }>('/dpn/registration', {
      method: 'POST',
      body: {},
    })
    return { result: done }
  })
  .mutation()

export const dpnCountryMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(z.object({ country: z.string().length(2).nullable() }))
  .loader(async ({ input }) => {
    return { dpn: await coreRequest<{ country: string | null }>('/dpn/country', { method: 'PUT', body: input }) }
  })
  .mutation()
