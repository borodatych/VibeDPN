import { serverEnv } from '@/modules/env/server'
import '@point0/core/server-only'
import { postgresBackplane } from '@point0/engine/backplane/postgres'
import postgres from 'postgres'

// DATABASE_URL is Prisma-flavored: its `?schema=` is a Prisma extension, not a real Postgres parameter —
// postgres.js forwards unknown params to the server, which refuses the connection. Strip it for this client.
const url = new URL(serverEnv.DATABASE_URL)
url.searchParams.delete('schema')

/**
 * The socket backplane: cross-process delivery over the same Postgres the app already runs — a LISTEN/NOTIFY bus plus
 * an unlogged KV table. Needs a direct connection — not a transaction-mode pooler.
 *
 * `max: 3` — a small own pool next to Prisma's (LISTEN holds its own dedicated connection outside it). `onnotice`
 * silences the boot-time "relation already exists, skipping" notices. `schema` — pg-boss style own schema, so `prisma
 * migrate` never reads the backplane tables as drift. `closeClient` — this client exists solely for the backplane, so
 * the adapter closes it on dispose.
 *
 * `engine.ts` reaches this module through a lazy `backplane` factory the engine calls on server start only, so nothing
 * here — the client or its env read — runs when a build or codegen loads the engine config.
 *
 * @tags socket, backplane, db
 * @related appChannel, prisma
 */
export const backplane = postgresBackplane(postgres(url.toString(), { max: 3, onnotice: () => {} }), {
  schema: 'point0',
  closeClient: true,
})
