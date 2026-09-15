import { useHead } from '@unhead/react'
import { Section } from '@/components/ui/section'
import { generalLayout } from '@/layouts/general'
import { SignInForm } from '@/modules/auth/components/sign-in'
import { redirectAuthorizedPlugin } from '@/modules/auth/plugins'
import { useT } from '@/modules/i18n/use-t'

export const signInPage = generalLayout.lets
  .page('/sign-in')
  .use(redirectAuthorizedPlugin)
  .page(() => {
    const t = useT()
    useHead({ title: t('auth.signIn') })
    return (
      <Section h1={t('auth.signIn')}>
        <SignInForm />
      </Section>
    )
  })
