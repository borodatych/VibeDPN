import { useHead } from '@unhead/react'
import { Card } from '@/components/ui/card'
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
    // the door of the box: centred in a card, and the header shows no pages behind it (layouts/general.tsx)
    return (
      <div className="flex justify-center pt-4 lg:pt-12">
        <Card compact h1={t('auth.title')} size="sm" className="w-full max-w-md">
          <SignInForm />
        </Card>
      </div>
    )
  })
