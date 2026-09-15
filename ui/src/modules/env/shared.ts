import { createEnv } from '@/modules/env/utils'
import { z } from 'zod'

/**
 * The env both sides may see — the shape, the handle, and the browser's allowlist.
 *
 * Shape and handle live together because validation is lazy: `createEnv` only defines getters, so declaring a variable
 * costs nothing until something reads it. There is no "shape file" to import when you want the schema without the
 * validation — `sharedEnv.shape` is right there.
 *
 * `clientEnvShape` lives here too, and that is deliberate rather than a leftover. What reaches the browser is decided
 * by the **server**, which injects `clientEnvKeys` into every page it serves (`engine.ts` → `clients[].env.vars`), so
 * the list is a shared fact and `engine.ts` has to be able to read it from a module with no side effects. The matching
 * `clientEnv` handle cannot live here for exactly that reason: it carries browser-only side effects (see `client.ts`).
 *
 * @tags env, zod
 * @related createEnv, clientEnv, serverEnv
 */

/** Variables that mean the same thing on both sides — URLs, public ids, modes. Never a secret. */
export const sharedEnvShape = {
  HOST_ENV: z.enum(['local', 'dev', 'prod']),
  NODE_ENV: z.enum(['development', 'test', 'production']),
  SERVER_URL: z.string().min(1),
  CLIENT_URL: z.string().min(1),
  LOG_LEVEL: z
    .enum(['trace', 'debug', 'info', 'warn', 'error', 'fatal'])
    .default(process.env.NODE_ENV === 'production' ? 'info' : 'debug'),
  LOG_MODE: z.enum(['json', 'pretty']).default(process.env.NODE_ENV === 'production' ? 'json' : 'pretty'),
  LOG_FILTER: z.string().optional(),

  // Identifier of the deployed source code (usually the git commit), used as the Sentry/Mixpanel/Axiom release and for
  // cache-busting. On Railway it's resolved at runtime from the injected RAILWAY_GIT_COMMIT_SHA (see index.server.ts);
  // set it explicitly to override. Required outside local so a deploy never ships without a release tag; empty in local.
  SOURCE_VERSION: z.string().optional(),

  // Mixpanel project token — one token drives both sides. Public by design (injected into the page at runtime, not baked
  // into the bundle), so it lives in the shared shape. Required outside local (HOST_ENV != local); empty in local
  // disables Mixpanel. See @/modules/mixpanel/README.md.
  MIXPANEL_PROJECT_TOKEN: z.string().optional(),
}

/**
 * Env shared by server and client. Lazily validated — reading a variable validates just that one; the app entries call
 * `validate()` (`serverEnv` / `clientEnv`) to check the whole set up front.
 */
export const sharedEnv = createEnv('shared', sharedEnvShape)

/**
 * Everything exposed to the browser: the shared variables plus the client-only public ones. Add client-only keys here.
 *
 * Never add secrets — these values reach the browser. They are **not** baked into the bundle: the server injects each
 * key's runtime value into every served page, so they resolve at runtime, not build time.
 */
export const clientEnvShape = {
  ...sharedEnvShape,
  // any client env variables can be here
  // SOMTHING: z.string().min(1),

  // Public DSN of the browser Sentry project. Injected into the page at runtime. Required outside local.
  SENTRY_DSN_CLIENT: z.string().optional(),
}

/** The allowlist of names the engine injects into every served page — see `engine.ts` (`clients[].env.vars`). */
export const clientEnvKeys = Object.keys(clientEnvShape)
