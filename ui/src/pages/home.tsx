import { Prose } from '@/components/ui/prose'
import { Section, Sections } from '@/components/ui/section'
import { generalLayout } from '@/layouts/general'
import { redirectUnauthorizedPlugin } from '@/modules/auth/plugins'

export const homePage = generalLayout.lets
  .page('/')
  .head({
    title: 'VibeDPN',
    titleTemplate: null,
  })
  .use(redirectUnauthorizedPlugin)
  .page(() => {
    return (
      <Sections gap="lg">
        <Section h1="VibeDPN">
          <Prose size="lg">
            <p>The box panel. Status, devices and the node come in the next screens.</p>
          </Prose>
        </Section>
      </Sections>
    )
  })
