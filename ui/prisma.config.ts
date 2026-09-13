import { defineConfig, env } from 'prisma/config'
import { config as loadEnv } from 'dotenv'

// eslint-disable-next-line no-restricted-properties -- Prisma CLI config: it runs outside the app and LOADS the env here
loadEnv({ path: [`.env.${process.env.NODE_ENV}`, '.env'] })

// `prisma generate` never connects to the database, so it must not require
// DATABASE_URL — otherwise building the image in CI/Docker fails without a DB.
// Only `generate` gets a throwaway URL; every other command keeps the strict
// env() so a missing DATABASE_URL still fails fast.
const generating = process.argv.includes('generate')

export default defineConfig({
  schema: 'src/modules/prisma/schema.prisma',
  migrations: {
    path: 'src/modules/prisma/migrations',
  },
  datasource: {
    // eslint-disable-next-line no-restricted-properties -- Prisma CLI config: the app's env handles are not loaded here
    url: generating ? (process.env.DATABASE_URL ?? 'postgresql://generate') : env('DATABASE_URL'),
  },
})
