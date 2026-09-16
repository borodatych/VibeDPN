import { root } from '@/lib/root'
import { AppError } from '@/lib/error'
import { authorizedOnlyPlugin } from '@/modules/auth/plugins'
import { coreFetch } from '@/modules/core/client'
import { EVENT_KINDS, HOUR_SECONDS, type BoxEvent, type WifiClient } from '@/features/events/shared'
import { z } from 'zod'

// Events are rare; a journal a quarter of a minute behind is current enough.
const EVENTS_REFRESH_MS = 15_000
// The connected time of a client moves every second, but its signal is what the owner watches.
const WIFI_REFRESH_MS = 10_000
const EVENTS_LIMIT = 1000
// 404: no LAN, or no access point on this box — the page explains instead of failing.
const NOT_HERE = 404
// 503: the access point runs no control socket or does not answer — shown, not thrown.
const UNAVAILABLE = 503

export const eventListQuery = root.lets
  .query()
  .use(authorizedOnlyPlugin)
  .input(z.object({ kind: z.enum(EVENT_KINDS).nullable(), hours: z.number().positive() }))
  .loader(async ({ input }) => {
    const since = Math.floor(Date.now() / 1000) - input.hours * HOUR_SECONDS
    const params = new URLSearchParams({ since: String(since), limit: String(EVENTS_LIMIT) })
    if (input.kind) {
      params.set('kind', input.kind)
    }
    const answer = await coreFetch<BoxEvent[]>(`/events?${params.toString()}`)
    if (answer.ok) {
      return { events: answer.body, reason: null }
    }
    if (answer.status === NOT_HERE) {
      return { events: [], reason: answer.detail }
    }
    throw new AppError(answer.detail, { status: answer.status })
  })
  .query({ refetchInterval: EVENTS_REFRESH_MS, staleTime: 0 })

export const wifiClientsQuery = root.lets
  .query()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    const answer = await coreFetch<WifiClient[]>('/wifi/clients')
    if (answer.ok) {
      return { clients: answer.body, available: true, reason: null }
    }
    if (answer.status === NOT_HERE) {
      return { clients: [], available: false, reason: null }
    }
    if (answer.status === UNAVAILABLE) {
      return { clients: [], available: true, reason: answer.detail }
    }
    throw new AppError(answer.detail, { status: answer.status })
  })
  .query({ refetchInterval: WIFI_REFRESH_MS, staleTime: 0 })
