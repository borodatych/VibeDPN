import { root } from '@/lib/root'
import { authorizedOnlyPlugin } from '@/modules/auth/plugins'
import { coreFetch } from '@/modules/core/client'
import type { NodeStats } from '@/features/node/shared'
import { AppError } from '@/lib/error'

// Session totals and earnings move slowly; core itself may spend seconds asking the node.
const NODE_REFRESH_MS = 30_000

const NO_NODE = 404
const NODE_SILENT = 503

export const nodeStatsQuery = root.lets
  .query()
  .use(authorizedOnlyPlugin)
  .loader(async () => {
    const answer = await coreFetch<NodeStats>('/provider/stats')
    if (answer.ok) {
      return { stats: answer.body, reason: null }
    }
    if (answer.status === NO_NODE) {
      return { stats: null, reason: 'none' as const }
    }
    if (answer.status === NODE_SILENT) {
      return { stats: null, reason: answer.detail }
    }
    throw new AppError(answer.detail, { status: answer.status })
  })
  .query({
    refetchInterval: NODE_REFRESH_MS,
    staleTime: 0,
  })
