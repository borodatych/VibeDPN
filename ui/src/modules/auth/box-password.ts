import { serverEnv } from '@/modules/env/server'
import '@point0/core/server-only'

/**
 * What better-auth stores as the password of the box admin. The real secret is never in the database: it is the bcrypt
 * line `vibedpn init` wrote to `secrets/htpasswd`, the same password as the core API and the node panel, and changing it
 * with `init` takes effect on the next sign-in without touching the database.
 *
 * @tags rule, auth
 * @related verifyBoxPassword, createInitialAdmin
 */
export const BOX_PASSWORD_MARKER = 'vibedpn:htpasswd'

/** The only account: the user `vibedpn init` names in `htpasswd`. */
export const BOX_ADMIN_USER = 'admin'

/** better-auth wants an email; the box has no mail, so the admin gets a fixed local-only address. */
export const BOX_ADMIN_EMAIL = 'admin@vibedpn.lan'

export const hashBoxPassword = async (_password: string) => await Promise.resolve(BOX_PASSWORD_MARKER)

const readAdminHash = async (): Promise<string | null> => {
  const file = Bun.file(serverEnv.HTPASSWD_FILE)
  if (!(await file.exists())) {
    return null
  }
  for (const line of (await file.text()).split('\n')) {
    const separator = line.indexOf(':')
    if (separator > 0 && line.slice(0, separator) === BOX_ADMIN_USER) {
      return line.slice(separator + 1).trim()
    }
  }
  return null
}

/**
 * Accepts only an account whose stored hash is the marker (an account created any other way never signs in) and only the
 * password whose bcrypt is the `admin` line of `htpasswd`, read on every attempt.
 */
export const verifyBoxPassword = async ({ hash, password }: { hash: string; password: string }) => {
  if (hash !== BOX_PASSWORD_MARKER) {
    return false
  }
  const adminHash = await readAdminHash()
  if (!adminHash) {
    return false
  }
  return await Bun.password.verify(password, adminHash)
}
