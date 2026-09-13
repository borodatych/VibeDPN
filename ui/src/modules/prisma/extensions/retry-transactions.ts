import type { PrismaClient } from '@/generated/prisma/client'
import '@point0/core/server-only'
import { Prisma } from '@prisma/client/extension'
import { backOff } from 'exponential-backoff'

/**
 * Retries Prisma transactions when Prisma or Postgres returns a transaction error code.
 *
 * @tags prisma, extension
 * @id prisma-retryTransactions
 * @related prisma
 */
export const prismaExtensionRetryTransactions = (prisma: PrismaClient) =>
  Prisma.defineExtension({
    name: 'retryTransactions',
    client: {
      $transaction: async (...args: any) => {
        // eslint-disable-next-line prefer-spread
        return await backOff(async () => await prisma.$transaction.apply(prisma, args), {
          retry: (e) => {
            const normalCode: string | undefined = e.code
            // parse e.message like this
            // ConnectorError(ConnectorError { user_facing_error: None, kind: QueryError(PostgresError { code: "25P02", message: "current transaction is aborted, commands ignored until end of transaction block", severity: "ERROR", detail: None, column: None, hint: None }), transient: false })
            const secretCode: string | undefined = e.message.match(/PostgresError \{ code: "([^"]+)"/)?.[1]
            const code = normalCode || secretCode
            // See: https://www.prisma.io/docs/reference/api-reference/error-reference#p2034
            const isTransactionErrorCode = code === 'P2034' || code === '25P02'
            return isTransactionErrorCode
          },
          jitter: 'none',
          numOfAttempts: 6,
          timeMultiple: 2,
        })
      },
    } as { $transaction: (typeof prisma)['$transaction'] },
  }) as never
