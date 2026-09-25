import { root } from '@/lib/root'
import { AppError } from '@/lib/error'
import { authorizedOnlyPlugin } from '@/modules/auth/plugins'
import { coreFetch, coreRequest } from '@/modules/core/client'
import type { UpdateView } from '@/features/update/shared'

// An update runs for minutes; a look every few seconds shows it end without a flood of requests.
const REFRESH_MS = 5_000

export const updateQuery = root.lets
  .query()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    let answer
    try {
      answer = await coreFetch<UpdateView>('/update')
    } catch {
      // core does not answer at all: while the box updates, it restarts, and core with it
      return { update: null, restarting: true }
    }
    if (!answer.ok) {
      throw new AppError(answer.detail, { status: answer.status })
    }
    return { update: answer.body, restarting: false }
  })
  .query({ refetchInterval: REFRESH_MS, staleTime: 0 })

export const updateMutation = root.lets
  .mutation()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    return { update: await coreRequest<UpdateView>('/update', { method: 'POST', body: {} }) }
  })
  .mutation()
