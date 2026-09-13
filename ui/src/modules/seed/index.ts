import { createInitialAdmin } from '@/features/admin/init'
import { cleanDb, throwIfNotSafeToDestroyDb } from '@/modules/seed/utils'

/**
 * Wipe the local database and create the box admin. The box has one account and no fixtures of its own; add a loader
 * here when a screen needs local data. Run via `bun run seed`.
 *
 * @tags seed, dev
 * @related throwIfNotSafeToDestroyDb, cleanDb
 */
export const seed = async () => {
  throwIfNotSafeToDestroyDb('seed')
  await cleanDb()
  await createInitialAdmin()
}
