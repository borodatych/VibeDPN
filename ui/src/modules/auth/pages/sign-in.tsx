import { Section } from '@/components/ui/section'
import { generalLayout } from '@/layouts/general'
import { SignInForm } from '@/modules/auth/components/sign-in'
import { redirectAuthorizedPlugin } from '@/modules/auth/plugins'

export const signInPage = generalLayout.lets
  .page('/sign-in')
  .head('Sign In')
  .use(redirectAuthorizedPlugin)
  .page(() => {
    return (
      <Section h1="Sign In">
        <SignInForm />
      </Section>
    )
  })
