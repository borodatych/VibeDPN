import { root } from '@/lib/root'
import { authorizedOnlyPlugin } from '@/modules/auth/plugins'
import { coreFetch, coreRequest } from '@/modules/core/client'
import { AppError } from '@/lib/error'
import {
  RULE_VIAS,
  type DomainListView,
  type DomainRule,
  type JournalDevice,
  type JournalEntry,
  type LearnedName,
} from '@/features/rules/shared'
import { z } from 'zod'

// core polls the AdGuard query log every 2 s: the sniffer follows at the same pace.
const JOURNAL_REFRESH_MS = 2_000
const RULES_REFRESH_MS = 30_000
// 404: no LAN, or no AdGuard on this box — the page explains instead of failing.
const NOT_HERE = 404

const rulePath = (domain: string) => `/rules/${encodeURIComponent(domain)}`

export const ruleListQuery = root.lets
  .query()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    const answer = await coreFetch<DomainRule[]>('/rules')
    if (answer.ok) {
      return { rules: answer.body, reason: null }
    }
    if (answer.status === NOT_HERE) {
      return { rules: [], reason: answer.detail }
    }
    throw new AppError(answer.detail, { status: answer.status })
  })
  .query({ refetchInterval: RULES_REFRESH_MS, staleTime: 0 })

export const ruleSetMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(
    z.object({
      domain: z.string().trim().min(1),
      via: z.enum(RULE_VIAS),
      country: z.string().length(2).nullable(),
      uplink: z.string().min(1).nullable(),
      learn: z.boolean(),
      also: z.array(z.string().min(1)),
    }),
  )
  .loader(async ({ input: { domain, ...rule } }) => {
    return { rule: await coreRequest<DomainRule>(rulePath(domain), { method: 'PUT', body: rule }) }
  })
  .mutation()

export const ruleRemoveMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(z.object({ domain: z.string().min(1) }))
  .loader(async ({ input }) => {
    await coreRequest(rulePath(input.domain), { method: 'DELETE' })
    return { ok: true }
  })
  .mutation()

export const journalDevicesQuery = root.lets
  .query()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    const answer = await coreFetch<JournalDevice[]>('/dns/devices')
    if (answer.ok) {
      return { devices: answer.body, reason: null }
    }
    if (answer.status === NOT_HERE) {
      return { devices: [], reason: answer.detail }
    }
    throw new AppError(answer.detail, { status: answer.status })
  })
  .query({ refetchInterval: JOURNAL_REFRESH_MS, staleTime: 0 })

export const journalQuery = root.lets
  .query()
  .use(authorizedOnlyPlugin)
  .input(z.object({ client: z.string().min(1) }))
  .loader(async ({ input }) => {
    return {
      entries: await coreRequest<JournalEntry[]>(`/dns/journal/${encodeURIComponent(input.client)}`),
    }
  })
  .query({ refetchInterval: JOURNAL_REFRESH_MS, staleTime: 0 })

export const learnedListQuery = root.lets
  .query()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    const answer = await coreFetch<LearnedName[]>('/learned')
    if (answer.ok) {
      return { learned: answer.body, reason: null }
    }
    if (answer.status === NOT_HERE) {
      return { learned: [], reason: answer.detail }
    }
    throw new AppError(answer.detail, { status: answer.status })
  })
  .query({ refetchInterval: JOURNAL_REFRESH_MS * 5, staleTime: 0 })

export const learnedForgetMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(z.object({ name: z.string().min(1) }))
  .loader(async ({ input }) => {
    await coreRequest(`/learned/${encodeURIComponent(input.name)}`, { method: 'DELETE' })
    return { ok: true }
  })
  .mutation()

// core checks the lists every 10 s: a new list shows its copy within that.
const LISTS_REFRESH_MS = 10_000

export const domainListsQuery = root.lets
  .query()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    const answer = await coreFetch<DomainListView[]>('/lists')
    if (answer.ok) {
      return { lists: answer.body, reason: null }
    }
    if (answer.status === NOT_HERE) {
      return { lists: [], reason: answer.detail }
    }
    throw new AppError(answer.detail, { status: answer.status })
  })
  .query({ refetchInterval: LISTS_REFRESH_MS, staleTime: 0 })

export const domainListSetMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(
    z.object({
      url: z.string().trim().url(),
      via: z.enum(RULE_VIAS),
      country: z.string().length(2).nullable(),
      uplink: z.string().min(1).nullable(),
    }),
  )
  .loader(async ({ input }) => {
    return { list: await coreRequest<DomainListView>('/lists', { method: 'PUT', body: input }) }
  })
  .mutation()

export const domainListRemoveMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(z.object({ url: z.string().min(1) }))
  .loader(async ({ input }) => {
    await coreRequest(`/lists?url=${encodeURIComponent(input.url)}`, { method: 'DELETE' })
    return { ok: true }
  })
  .mutation()
