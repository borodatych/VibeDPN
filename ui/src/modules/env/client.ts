import { clientEnvShape } from '@/modules/env/shared'
import { createEnv } from '@/modules/env/utils'
import '@point0/core/client-only'

// Dev only: route client→server requests through the client origin (the Vite proxy) so SSR fetches skip CORS. Under
// `bun run start` the app server serves the client itself, so the client uses SERVER_URL as-is — overriding it would
// aim fetches at the (non-existent) dev client port. Env getters read `process.env` lazily, so mutating it before
// anything reads SERVER_URL suffices. No SSR? Drop this and use the @point0/cors plugin instead.
if (process.env.NODE_ENV !== 'production') {
  process.env.SERVER_URL = process.env.CLIENT_URL
} else if (typeof window !== 'undefined') {
  // A box panel is opened by its address or by its name (ui.host_name): the app server serves the client on either, so
  // the browser talks to the origin it is on. An absolute SERVER_URL would send sign-in to the address while the page
  // sits on the name, and the SameSite=strict session cookie would never reach the page.
  process.env.SERVER_URL = window.location.origin
  process.env.CLIENT_URL = window.location.origin
}

/**
 * Browser-side env. Lazily validated — `app.client.tsx` calls `clientEnv.validate()` at startup to fail fast. In dev
 * `SERVER_URL` is pointed at `CLIENT_URL` (see above) so SSR client→server requests skip CORS; in prod the URLs already
 * match.
 *
 * This file is the handle only; its shape lives in `shared.ts`. That is the one place the pattern bends, and it bends
 * for a reason: the **server** decides what reaches the browser and injects `clientEnvKeys` into every page, so it has
 * to read the key list — and this module is exactly what it must not import. The rewrite above would point the server
 * at its own client's URL, and `@point0/core/client-only` makes the compiler deny the import anyway.
 *
 * @tags env, zod
 * @related clientEnvShape, sharedEnv, serverEnv
 */
export const clientEnv = createEnv('client', clientEnvShape)
