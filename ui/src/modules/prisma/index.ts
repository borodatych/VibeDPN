import { PrismaClient } from '@/generated/prisma/client'
import { logger } from '@/lib/logger'
import { onShutdown } from '@/lib/shutdown'
import { serverEnv } from '@/modules/env/server'
import { prismaExtensionFindManyAndCount } from '@/modules/prisma/extensions/find-many-and-count'
import { prismaExtensionRetryTransactions } from '@/modules/prisma/extensions/retry-transactions'
import { splitQueryAndComment } from '@/modules/prisma/utils'
import '@point0/core/server-only'
import { PrismaPg } from '@prisma/adapter-pg'
import type { ITXClientDenyList } from '@prisma/client/runtime/client'
import { traceContext } from '@prisma/sqlcommenter-trace-context'

const l = logger.child('prisma')

const _prisma = new PrismaClient({
  adapter: new PrismaPg({ connectionString: serverEnv.DATABASE_URL }),
  comments: [traceContext()],
  log: [
    { level: 'error', emit: 'event' },
    { level: 'warn', emit: 'event' },
    { level: 'info', emit: 'event' },
    { level: 'query', emit: 'event' },
  ],
})

_prisma.$on('error', (event) => {
  const { message, ...rest } = event
  l.error(message, rest)
})
_prisma.$on('warn', (event) => {
  const { message, ...rest } = event
  l.warn(message, rest)
})
_prisma.$on('info', (event) => {
  const { message, ...rest } = event
  l.info(message, rest)
})
_prisma.$on('query', (event) => {
  const { params, query, ...rest } = event
  const { queryWithoutComment, queryCommentParsed } = splitQueryAndComment(query)
  l.info('Query', {
    query: queryWithoutComment,
    ...rest,
    ...(serverEnv.HOST_ENV !== 'prod' ? { params } : {}),
    ...queryCommentParsed,
  })
})

/**
 * Shared Prisma client used across the server. Connects lazily on the first query, and disconnects on shutdown — after
 * pg-boss and the HTTP engine have torn down, so nothing queries a closed client.
 *
 * Logs Prisma events and enables the project Prisma extensions.
 *
 * @tags prisma, data
 * @related prisma-migrations
 */
export const prisma = _prisma
  .$extends(prismaExtensionFindManyAndCount(_prisma))
  .$extends(prismaExtensionRetryTransactions(_prisma))

export type AppPrisma = typeof prisma
export type TxPrisma = Omit<AppPrisma, ITXClientDenyList>

onShutdown('prisma', async () => await prisma.$disconnect())
