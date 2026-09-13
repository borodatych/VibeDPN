import { useChanged } from '@/components/hooks/use-changed'
import { getMeQuery } from '@/modules/auth/api'
import { mixpanelIdentifyUser } from '@/modules/mixpanel/shared'

/**
 * Drives Mixpanel identity from the cached `me`: `identify` + People profile on sign-in, `reset` on sign-out. Reads
 * `getMeQuery` with `enabled: false` (mirrors the cache, no fetch). `useChanged` fires only on a real identity change,
 * not on the per-navigation reference churn of `me`. Mount once near the app root.
 *
 * @tags mixpanel, auth
 * @related mixpanelIdentifyUser, getMeQuery, MixpanelTrackPage, SentryTrackAuth
 */
export const MixpanelTrackAuth = (): null => {
  const result = getMeQuery.useQuery(undefined, { enabled: false }).data?.me ?? null
  const session = result?.session ?? null
  const user = result?.user ?? null

  useChanged(
    () => {
      if (!user) {
        mixpanelIdentifyUser(null)
        return
      }
      const impersonated = session?.impersonatedBy ?? undefined
      mixpanelIdentifyUser({
        id: user.id,
        email: user.email,
        name: user.name,
        avatar: user.image ?? undefined,
        createdAt: user.createdAt,
        role: user.role ?? undefined,
        sn: user.sn,
        ...(impersonated ? { impersonated } : {}),
      })
    },
    [user, session],
    { initial: true },
  )

  return null
}
