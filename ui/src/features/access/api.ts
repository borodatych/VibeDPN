import { root } from '@/lib/root'
import { AppError } from '@/lib/error'
import { authorizedOnlyPlugin } from '@/modules/auth/plugins'
import { coreFetch, coreRequest } from '@/modules/core/client'
import {
  MAX_DDNS_URL_BYTES,
  PERSON_NAME,
  type AccessLink,
  type AccessServer,
  type Ddns,
} from '@/features/access/shared'
import { z } from 'zod'

// The host applies a change within seconds; the page follows it closely while it is open.
const REFRESH_MS = 3_000
// 404: this core keeps no files for an access server — the page explains instead of failing.
const NOT_HERE = 404

export const accessQuery = root.lets
  .query()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    const answer = await coreFetch<AccessServer>('/access')
    if (answer.ok) {
      return { server: answer.body, reason: null }
    }
    if (answer.status === NOT_HERE) {
      return { server: null, reason: answer.detail }
    }
    throw new AppError(answer.detail, { status: answer.status })
  })
  .query({ refetchInterval: REFRESH_MS, staleTime: 0 })

export const accessMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  // a field left null stays as it is in config.yaml
  .input(
    z.object({
      enabled: z.boolean(),
      address: z.string().max(253).nullable(),
      target: z.string().max(253).nullable(),
    }),
  )
  .loader(async ({ input }) => {
    return { server: await coreRequest<AccessServer>('/access', { method: 'PUT', body: input }) }
  })
  .mutation()

export const personAddMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(z.object({ name: z.string().regex(PERSON_NAME) }))
  .loader(async ({ input }) => {
    return { link: await coreRequest<AccessLink>('/access/people', { method: 'POST', body: input }) }
  })
  .mutation()

// A mutation, not a query: the link lets its holder in, so it is fetched when the owner asks and never cached.
export const personLinkMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(z.object({ name: z.string().regex(PERSON_NAME) }))
  .loader(async ({ input }) => {
    return { link: await coreRequest<AccessLink>(`/access/people/${encodeURIComponent(input.name)}`) }
  })
  .mutation()

export const personRemoveMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(z.object({ name: z.string().regex(PERSON_NAME) }))
  .loader(async ({ input }) => {
    await coreRequest<null>(`/access/people/${encodeURIComponent(input.name)}`, { method: 'DELETE' })
    return { removed: input.name }
  })
  .mutation()

export const ddnsQuery = root.lets
  .query()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    const answer = await coreFetch<Ddns>('/ddns')
    if (answer.ok) {
      return { ddns: answer.body, reason: null }
    }
    if (answer.status === NOT_HERE) {
      return { ddns: null, reason: answer.detail }
    }
    throw new AppError(answer.detail, { status: answer.status })
  })
  .query({ refetchInterval: REFRESH_MS, staleTime: 0 })

export const ddnsMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  // The URL goes to core and stays there; `null` means "keep the one you have".
  .input(z.object({ enabled: z.boolean(), url: z.string().max(MAX_DDNS_URL_BYTES).nullable() }))
  .loader(async ({ input }) => {
    return { ddns: await coreRequest<Ddns>('/ddns', { method: 'PUT', body: input }) }
  })
  .mutation()
