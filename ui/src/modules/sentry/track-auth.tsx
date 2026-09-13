import { useChanged } from '@/components/hooks/use-changed'
import { getMeQuery } from '@/modules/auth/api'
import { sentrySetUser } from '@/modules/sentry/shared'

/**
 * Mirrors the cached `me` onto Sentry events: set user on sign-in, clear on sign-out. `useChanged` fires only on a real
 * identity change, not on the per-navigation reference churn of `me`.
 *
 * @tags sentry, auth
 * @related sentrySetUser, getMeQuery, MixpanelTrackAuth
 */
export const SentryTrackAuth = (): null => {
  const result = getMeQuery.useQuery(undefined, { enabled: false }).data?.me ?? null
  const session = result?.session ?? null
  const user = result?.user ?? null

  useChanged(
    () => {
      if (!user) {
        sentrySetUser(null)
        return
      }
      const impersonated = session?.impersonatedBy ?? undefined
      sentrySetUser({ id: user.id, email: user.email, username: user.name, ...(impersonated ? { impersonated } : {}) })
    },
    [user, session],
    { initial: true },
  )

  return null
}
