import { sharedEnvShape } from '@/modules/env/shared'
import { createEnv } from '@/modules/env/utils'
import '@point0/core/server-only'
import { z } from 'zod'

const isProdNodeEnv = process.env.NODE_ENV === 'production'

/**
 * Server-side env (shared shape + server-only secrets). Lazily validated — `app.server.ts` calls `serverEnv.validate()`
 * at startup to fail fast; reading any single variable validates just that one.
 *
 * Read server config only via `@/modules/env` (`serverEnv` / `sharedEnv`) — never `process.env` directly in features;
 * it's schema-validated and typed. To add a secret: extend the shape below and add the variable to `env.example`.
 *
 * @tags rule, env, zod
 * @related sharedEnvShape, clientEnv
 */
export const serverEnv = createEnv('server', {
  ...sharedEnvShape,
  SERVER_PORT: isProdNodeEnv ? z.string().optional() : z.string().min(1),
  CLIENT_PORT: isProdNodeEnv ? z.string().optional() : z.string().min(1),
  PORT: isProdNodeEnv ? z.string().min(1) : z.string().optional(),
  DATABASE_URL: z.string().min(1),
  BETTER_AUTH_SECRET: z.string().min(32),
  // The bcrypt line of the box password (`vibedpn init`); read on every sign-in, see verifyBoxPassword.
  HTPASSWD_FILE: z.string().min(1).default('/run/secrets/htpasswd'),
  // Port of the core API on 127.0.0.1; reached only through coreApiProxy.
  CORE_API_PORT: z.string().regex(/^\d{1,5}$/),
  // The LAN address the panel listens on. Required in production: Bun would listen on every interface otherwise.
  UI_LISTEN_HOST: isProdNodeEnv ? z.ipv4() : z.ipv4().optional(),

  // Telemetry is optional in every HOST_ENV: a box sends nothing anywhere unless its owner configures it.
  SENTRY_DSN_SERVER: z.string().optional(),

  // Axiom — server-only log store + metrics. Required outside local; empty in local disables it (like Sentry/Mixpanel).
  // The app uses a BASIC ingest token, NOT the advanced AXIOM_TOKEN_ROOT (provisioning-only, never read here). AXIOM_EDGE
  // is the region's ingest edge domain (e.g. eu-central-1.aws.edge.axiom.co) — datasets live in a region and ingest must
  // hit it, not the global control plane. Dataset names are fixed (`logs` / `metrics`). See @/modules/axiom/README.md.
  AXIOM_TOKEN: z.string().optional(),
  AXIOM_EDGE: z.string().optional(),
})
