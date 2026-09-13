import { logger } from '@/lib/logger'
import { shutdown } from '@/lib/shutdown'
import { BOX_ADMIN_EMAIL, BOX_ADMIN_USER, BOX_PASSWORD_MARKER } from '@/modules/auth/box-password'
import { authServer } from '@/modules/auth/server'
import { prisma } from '@/modules/prisma'

const l = logger.child('admin')

/**
 * Ensure the box admin exists. Called from server startup.
 *
 * The password is not taken from env: better-auth stores only the marker, and sign-in checks `secrets/htpasswd`
 * (`verifyBoxPassword`). Shuts the process down on failure.
 *
 * @tags admin, bootstrap
 * @related verifyBoxPassword
 */
export const createInitialAdmin = async () => {
  try {
    const exAdmin = await prisma.user.findUnique({ where: { email: BOX_ADMIN_EMAIL } })
    if (exAdmin) {
      if (exAdmin.role !== 'admin') {
        await prisma.user.update({ where: { id: exAdmin.id }, data: { role: 'admin' } })
        l.info('Updated initial admin role', { email: BOX_ADMIN_EMAIL })
      }
      return
    }
    await authServer.api.createUser({
      body: {
        email: BOX_ADMIN_EMAIL,
        // hashed into BOX_PASSWORD_MARKER; never used to sign in
        password: BOX_PASSWORD_MARKER,
        name: BOX_ADMIN_USER,
        role: 'admin',
      },
    })
    l.info('Created initial admin', { email: BOX_ADMIN_EMAIL })
  } catch (error) {
    l.error('Error creating initial admin', { error })
    void shutdown(1)
  }
}
