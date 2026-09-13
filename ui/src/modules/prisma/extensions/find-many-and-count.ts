import type { PrismaClient } from '@/generated/prisma/client'
import '@point0/core/server-only'
import { Prisma } from '@prisma/client/extension'

/**
 * Adds `findManyAndCount` to every Prisma model.
 *
 * It returns the matching items and the total count in a single transaction.
 *
 * @example
 *   const [items, total] = await prisma.user.findManyAndCount({
 *     where: {
 *       subscriptionExpiresAt: {
 *         gt: new Date(),
 *       },
 *     },
 *   })
 *
 * @example
 *   // When cursor pagination adds a cursor boundary to `where`, pass the cursor field
 *   // so it can be excluded from the count query.
 *   const [items, total] = await prisma.user.findManyAndCount(
 *     {
 *       where: {
 *         subscriptionExpiresAt: {
 *           gt: new Date(),
 *         },
 *         sn: {
 *           lte: 100,
 *         },
 *       },
 *       take: 10,
 *       skip: 0,
 *     },
 *     'sn',
 *   )
 *
 * @tags prisma, extension
 * @related prisma
 */
export const prismaExtensionFindManyAndCount = (prisma: PrismaClient) =>
  Prisma.defineExtension({
    name: 'findManyAndCount',
    model: {
      $allModels: {
        /**
         * Find and return items and total available count
         * https://github.com/prisma/prisma/issues/7550#issuecomment-2236046270
         */
        async findManyAndCount<TModel, TArgs>(
          this: TModel,
          args: Prisma.Exact<TArgs, Prisma.Args<TModel, 'findMany'>>,
          cursorKey?: string,
        ): Promise<[Prisma.Result<TModel, TArgs, 'findMany'>, number]> {
          const context = Prisma.getExtensionContext(this)
          const countWhere = { ...(args as any).where }
          if (cursorKey) {
            delete countWhere[cursorKey]
          }
          return await (prisma.$transaction(
            [(context as any).findMany(args), (context as any).count({ where: countWhere })],
            {
              isolationLevel: 'ReadCommitted',
            },
          ) as Promise<[Prisma.Result<TModel, TArgs, 'findMany'>, number]>)
        },
      },
    },
  })
