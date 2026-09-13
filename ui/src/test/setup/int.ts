// in .env.test we have different urls for e2e tests in dev mode

import { engine } from '@/engine'

// but in integration tests we will have only server
// eslint-disable-next-line no-restricted-properties -- test setup: it SETS the variable, before preload resolves env
process.env.CLIENT_URL = process.env.SERVER_URL

await import('@/preload')

// Prepare the engine once for the whole integration run. Prisma connects lazily on first use (the first query), so
// nothing touches the database here. `@/preload` runs first so env is loaded before any service module reads it.
await engine.prepare()

export {}
