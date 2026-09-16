import { root } from '@/lib/root'
import { AppError } from '@/lib/error'
import { authorizedOnlyPlugin } from '@/modules/auth/plugins'
import { coreFetch, coreRequest } from '@/modules/core/client'
import { MAX_WG_FILE_BYTES, WG_EXIT_NAME, type TorExit, type WgExits } from '@/features/uplinks/shared'
import { z } from 'zod'

// The host applies a change within seconds; the page follows it closely while it is open.
const EXITS_REFRESH_MS = 3_000
// 404: no LAN on this box — the page explains instead of failing.
const NOT_HERE = 404

export const wgExitsQuery = root.lets
  .query()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    const answer = await coreFetch<WgExits>('/uplinks/wg')
    if (answer.ok) {
      return { exits: answer.body, reason: null }
    }
    if (answer.status === NOT_HERE) {
      return { exits: null, reason: answer.detail }
    }
    throw new AppError(answer.detail, { status: answer.status })
  })
  .query({ refetchInterval: EXITS_REFRESH_MS, staleTime: 0 })

export const torExitQuery = root.lets
  .query()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    const answer = await coreFetch<TorExit>('/uplinks/tor')
    if (answer.ok) {
      return { tor: answer.body, reason: null }
    }
    if (answer.status === NOT_HERE) {
      return { tor: null, reason: answer.detail }
    }
    throw new AppError(answer.detail, { status: answer.status })
  })
  .query({ refetchInterval: EXITS_REFRESH_MS, staleTime: 0 })

export const torExitMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(z.object({ enabled: z.boolean() }))
  .loader(async ({ input }) => {
    return { tor: await coreRequest<TorExit>('/uplinks/tor', { method: 'PUT', body: input }) }
  })
  .mutation()

export const wgExitAddMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(
    z.object({
      name: z.string().regex(WG_EXIT_NAME),
      config: z.string().min(1).max(MAX_WG_FILE_BYTES),
    }),
  )
  .loader(async ({ input }) => {
    return { exits: await coreRequest<WgExits>('/uplinks/wg', { method: 'POST', body: input }) }
  })
  .mutation()

export const wgExitRemoveMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(z.object({ name: z.string().regex(WG_EXIT_NAME) }))
  .loader(async ({ input }) => {
    return {
      exits: await coreRequest<WgExits>(`/uplinks/wg/${encodeURIComponent(input.name)}`, { method: 'DELETE' }),
    }
  })
  .mutation()
