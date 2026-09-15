import { useHead } from '@unhead/react'
import { useFForm } from '@/modules/form/core/hook'
import { generalLayout } from '@/layouts/general'
import { useT } from '@/modules/i18n/use-t'
import { navigate } from '@/lib/navigation'
import { signOut } from '@/modules/auth/client'
import { mixpanelTrackEvent } from '@/modules/mixpanel/shared'

export const signOutPage = generalLayout.lets.page('/sign-out').page(({ LoadingComponent }) => {
  const t = useT()
  useHead({ title: t('auth.signOut') })
  useFForm({
    onSubmit: () => {
      // Track before `signOut` triggers `MixpanelTrackAuth` → `mixpanel.reset()`, so the event still belongs to this user.
      mixpanelTrackEvent('Signed Out')
      signOut({
        onSettled: () => {
          void navigate('signIn', undefined, { replace: true })
        },
      })
    },
    submitOnMount: true,
  })
  return <LoadingComponent />
})
