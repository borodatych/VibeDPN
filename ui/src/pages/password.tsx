import { useHead } from '@unhead/react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Section, Sections } from '@/components/ui/section'
import { panelPasswordMutation } from '@/features/password/api'
import { PASSWORD_MAX_BYTES, PASSWORD_MIN, passwordProblem } from '@/features/password/shared'
import { generalLayout } from '@/layouts/general'
import { redirectUnauthorizedPlugin } from '@/modules/auth/plugins'
import { useT } from '@/modules/i18n/use-t'
import { type ComponentProps, useState } from 'react'

const PasswordInput = ({ label, ...props }: ComponentProps<typeof Input> & { label: string }) => (
  <label className="block max-w-sm space-y-1">
    <span className="block text-sm">{label}</span>
    <Input type="password" spellCheck={false} {...props} />
  </label>
)

export const passwordPage = generalLayout.lets
  .page('/password')
  .use(redirectUnauthorizedPlugin)
  .page(() => {
    const t = useT()
    useHead({ title: t('nav.password') })
    const save = panelPasswordMutation.useMutation()
    const [current, setCurrent] = useState('')
    const [value, setValue] = useState('')
    const [repeat, setRepeat] = useState('')
    const typed = current || value || repeat
    const problem = typed ? passwordProblem(current, value, repeat) : null
    const limits = { min: PASSWORD_MIN, max: PASSWORD_MAX_BYTES }
    const submit = async () => {
      const answer = await save.mutateAsync({ current, new: value })
      setCurrent('')
      if (!answer.wrongCurrent) {
        setValue('')
        setRepeat('')
      }
    }
    const result = save.data
    return (
      <Sections gap="lg">
        <Section h1={t('password.title')} description={t('password.description')}>
          <div className="space-y-3">
            <PasswordInput
              label={t('password.current')}
              value={current}
              autoComplete="current-password"
              onChange={(event) => setCurrent(event.target.value)}
            />
            <PasswordInput
              label={t('password.new')}
              value={value}
              autoComplete="new-password"
              onChange={(event) => setValue(event.target.value)}
            />
            <PasswordInput
              label={t('password.repeat')}
              value={repeat}
              autoComplete="new-password"
              onChange={(event) => setRepeat(event.target.value)}
            />
            <p className="text-xs text-muted-foreground">{t('password.hint', limits)}</p>
            <Button disabled={!typed || problem !== null} loading={save.isPending} onClick={() => void submit()}>
              {t('password.save')}
            </Button>
            {problem && <p className="text-sm text-destructive">{t(`password.problem.${problem}`, limits)}</p>}
            {save.isError && <p className="text-sm text-destructive">{save.error.message}</p>}
            {result?.wrongCurrent && <p className="text-sm text-destructive">{t('password.wrongCurrent')}</p>}
            {result?.password && (
              <div className="space-y-1 text-sm">
                <p>{t('password.done')}</p>
                {result.password.later.length > 0 && (
                  <p className="text-muted-foreground">
                    {t('password.later', {
                      services: result.password.later.map((name) => t(`password.service.${name}`)).join(', '),
                    })}
                  </p>
                )}
              </div>
            )}
          </div>
        </Section>
      </Sections>
    )
  })
