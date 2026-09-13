import { logger } from '@/lib/logger'
import { serverEnv } from '@/modules/env/server'
import { prisma } from '@/modules/prisma'
import { env, getRequest } from '@point0/core'
import type { Request0 } from '@point0/core/request0'
import '@point0/core/server-only'
import { betterAuth } from 'better-auth'
import { hashBoxPassword, verifyBoxPassword } from './box-password'
import { CLIENT_IP_HEADER } from './client-ip'
import { prismaAdapter } from 'better-auth/adapters/prisma'
import { admin as adminPlugin, testUtils } from 'better-auth/plugins'

const l = logger.child('auth')

const SIGN_IN_PATH = '/sign-in/email'
const SIGN_IN_WINDOW_SECONDS = 300
const SIGN_IN_MAX_ATTEMPTS = 5

/**
 * Origins the panel is opened from: the LAN address (`CLIENT_URL`) and the box name devices resolve through AdGuard
 * (`UI_HOST_NAME`, `ui.host_name` in config.yaml), on the same scheme and port. Anything else is refused by origin.
 */
const panelOrigins = () => {
  const byAddress = new URL(serverEnv.CLIENT_URL)
  const origins = [byAddress.origin]
  const hostName = serverEnv.UI_HOST_NAME
  if (hostName) {
    const byName = new URL(byAddress.origin)
    byName.hostname = hostName
    origins.push(byName.origin)
  }
  return origins
}

/**
 * Configured better-auth instance for the server.
 *
 * Use `authServer.api.*` for server-side auth operations. For session reads use `getMe` instead, so caching happens.
 *
 * @tags auth, better-auth
 * @related getMe, authClient, trySyncLinkedSocialAccount
 */
export const authServer = betterAuth({
  secret: serverEnv.BETTER_AUTH_SECRET,
  baseURL: serverEnv.SERVER_URL,
  trustedOrigins: panelOrigins(),
  database: prismaAdapter(prisma, {
    provider: 'postgresql',
  }),
  logger: {
    log: (level, message, ...args) => {
      l.log({ level, input: message, props: args.length > 0 ? { args } : undefined })
    },
  },
  advanced: {
    database: {
      generateId: 'uuid',
    },
    // Only the socket peer, set by withSocketClientIp; forwarding headers from the LAN are claims, not facts.
    ipAddress: {
      ipAddressHeaders: [CLIENT_IP_HEADER],
    },
    // The panel is plain HTTP on the LAN: a Secure cookie would never come back to it.
    useSecureCookies: false,
    cookies: {
      session_token: { attributes: { sameSite: 'strict' } },
    },
  },
  // On in every mode, not only in production: one password guards the panel, the core API and the node panel.
  rateLimit: {
    enabled: true,
    customRules: {
      // The built-in 3 per 10 s still lets ~1000 passwords an hour through.
      [SIGN_IN_PATH]: { window: SIGN_IN_WINDOW_SECONDS, max: SIGN_IN_MAX_ATTEMPTS },
    },
  },
  plugins: [adminPlugin(), ...(env.mode.is.test ? [testUtils()] : [])],
  databaseHooks: {
    session: {
      create: {
        after: async (session) => {
          l.info('Signed in', { userId: session.userId, ip: session.ipAddress ?? null })
        },
      },
      delete: {
        // Every death of a session funnels here (sign-out, revoke, expiry): tell its live connections, then re-auth them.
        // Lazy import: `lib/root.tsx` mounts `authServer`, and the socket points grow from `root`.
        after: async (session) => {
          const { sessionEndedHandler, sessionSpace } = await import('@/modules/auth/socket')
          try {
            sessionEndedHandler.sendToClient(undefined, { room: { sessionId: session.id } })
            await sessionSpace.refresh({ room: { sessionId: session.id } })
          } catch (error) {
            l.warn('Session-ended socket notify failed', { sessionId: session.id, error })
          }
        },
      },
    },
  },
  emailAndPassword: {
    enabled: true,
    // The box has one account, created at start (createInitialAdmin); nobody signs up.
    disableSignUp: true,
    password: {
      hash: hashBoxPassword,
      verify: verifyBoxPassword,
    },
  },
  user: {
    additionalFields: {
      sn: {
        type: 'number',
        input: false,
      },
    },
  },
})

/**
 * Bypass the request cache and rerun the session read. Use after mutating role or linked accounts when the next read in
 * the same request must see the change.
 *
 * @tags auth
 * @related getMe
 */
export const getMeFresh = async ({ request }: { request?: Request0 } = {}) => {
  request ??= getRequest()
  const headers = request.original.headers
  const result = await authServer.api.getSession({ headers })
  if (!result) {
    request.cache.me = null
    return null
  }
  const admin = result.user.role === 'admin'
  const me = {
    ...result,
    user: result.user,
    admin,
  }
  request.cache.me = me
  return me
}

// we can decalre global cache types for request0
declare module '@point0/core/request0' {
  interface RequestCache {
    me?: Me | null
  }
}

export type Me = NonNullable<Awaited<ReturnType<typeof getMeFresh>>>

/**
 * Read whatever `getMe` stored on the current request, without running it. Returns `undefined` when `getMe` hasn't run
 * yet, `null` for anonymous, `Me` otherwise.
 *
 * @tags auth
 * @related getMe
 */
export const getMeCached = ({ request }: { request?: Request0 } = {}): Me | undefined | null => {
  request ??= getRequest()
  return request.cache.me
}

/**
 * Canonical server-side session read. Cached per request. Returns `null` for anonymous users. On the client use
 * `getMeQuery` instead.
 *
 * @tags auth
 * @related getMeFresh, getMeCached, getMeQuery
 */
export const getMe = async ({ request }: { request?: Request0 } = {}) => {
  request ??= getRequest()
  if (request.cache.me !== undefined) {
    return request.cache.me
  }
  return await getMeFresh({ request })
}
