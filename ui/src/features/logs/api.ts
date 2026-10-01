import { root } from '@/lib/root'
import { authorizedOnlyPlugin } from '@/modules/auth/plugins'
import { coreRequest } from '@/modules/core/client'
import type { LogsView } from '@/features/logs/shared'
import { z } from 'zod'

// The host reads a log in a second; a look every few seconds shows the lines soon after
const REFRESH_MS = 3_000

export const logsQuery = root.lets
  .query()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    return { logs: await coreRequest<LogsView>('/logs') }
  })
  .query({ refetchInterval: REFRESH_MS, staleTime: 0 })

export const logsMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .input(z.object({ service: z.string(), tail: z.number().int() }))
  .loader(async ({ input }) => {
    return { logs: await coreRequest<LogsView>('/logs', { method: 'POST', body: input }) }
  })
  .mutation()
