import { serverEnv } from '@/modules/env/server'
import { prisma } from '@/modules/prisma'

/**
 * Refuse to run when the environment looks like staging/production.
 *
 * Requires `NODE_ENV !== 'production'`, `HOST_ENV === 'local'`, and `DATABASE_URL` to contain `localhost`. Call this at
 * the start of every destructive seed operation.
 *
 * @tags rule, seed, safety, data
 */
export const throwIfNotSafeToDestroyDb = (subject = 'destroy database') => {
  if (serverEnv.NODE_ENV === 'production') {
    throw new Error(`Cannot ${subject} in production NODE_ENV`)
  }
  if (serverEnv.HOST_ENV !== 'local') {
    throw new Error(`Cannot ${subject} in non-local HOST_ENV`)
  }
  if (!serverEnv.DATABASE_URL.includes('localhost')) {
    throw new Error('Cannot clean database if DATABASE_URL is not localhost')
  }
}

/**
 * Truncate every table in the `public` schema (except `_prisma_migrations`), restarting identities and cascading
 * foreign keys. Does not run migrations — assumes the Prisma schema is current.
 *
 * @tags seed, db
 */
export const cleanDb = async () => {
  throwIfNotSafeToDestroyDb('clean database')
  await prisma.$executeRawUnsafe(`
    DO $$
    DECLARE
      tables text;
    BEGIN
      SELECT string_agg(format('%I.%I', schemaname, tablename), ', ')
      INTO tables
      FROM pg_tables
      WHERE schemaname IN ('public')
        AND tablename <> '_prisma_migrations';

      IF tables IS NOT NULL THEN
        EXECUTE 'TRUNCATE TABLE ' || tables || ' RESTART IDENTITY CASCADE';
      END IF;
    END $$;
  `)
}
