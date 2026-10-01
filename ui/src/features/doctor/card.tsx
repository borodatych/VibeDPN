import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Section } from '@/components/ui/section'
import { doctorMutation, doctorQuery } from '@/features/doctor/api'
import { countVerdicts, problemsFirst, type Check, type Verdict } from '@/features/doctor/shared'
import { useLanguage, useT } from '@/modules/i18n/use-t'
import { formatDate } from '@/utils/date'
import { useState } from 'react'

const VERDICT_BADGE: Record<Verdict, 'success' | 'warning' | 'destructive'> = {
  ok: 'success',
  warn: 'warning',
  fail: 'destructive',
}

const CheckLine = ({ check }: { check: Check }) => {
  const t = useT()
  return (
    <li className="flex flex-wrap items-baseline gap-2 text-sm">
      <Badge variant={VERDICT_BADGE[check.verdict]}>{t(`doctor.verdict.${check.verdict}`)}</Badge>
      <span className="font-accent">{check.name}</span>
      {/* the explanation is doctor's own, in English, as core's errors are elsewhere in the panel */}
      <span className="text-muted-foreground">
        {check.detail}
        {check.hint && ` — ${check.hint}`}
      </span>
    </li>
  )
}

/**
 * The check of the box: the last report, kept by the host every day and when asked here
 *
 * The host runs `vibedpn doctor` (decision 37): most checks see what only the host sees
 *
 * @tags doctor
 */
export const DoctorCard = () => {
  const t = useT()
  const language = useLanguage()
  const view = doctorQuery.useQuery().data?.doctor ?? null
  const ask = doctorMutation.useMutation()
  const [showOk, setShowOk] = useState(false)
  const run = async (network: boolean) => {
    await ask.mutateAsync({ network })
    await doctorQuery.refetchQuery()
  }
  const pending = view?.state.pending ?? false
  const report = view?.report ?? null
  const checks = report ? problemsFirst(report.checks) : []
  const counts = countVerdicts(checks)
  const problems = checks.filter((check) => check.verdict !== 'ok')
  const fine = checks.filter((check) => check.verdict === 'ok')
  return (
    <Section h2={t('doctor.title')} description={t('doctor.description')}>
      <div className="space-y-3">
        {report ? (
          <p className="text-sm">
            {t(report.network ? 'doctor.summary.network' : 'doctor.summary.local', {
              time: formatDate(new Date(report.finished_at * 1000), 'date-time-nice', language),
              ok: counts.ok,
              warn: counts.warn,
              fail: counts.fail,
            })}
          </p>
        ) : (
          <p className="text-sm text-muted-foreground">{t('doctor.none')}</p>
        )}
        {pending && <p className="text-sm text-warning">{t('doctor.pending')}</p>}
        {!pending && view?.state.ok === false && (
          <p className="text-sm text-destructive">{t('doctor.failed', { message: view.state.message })}</p>
        )}
        {problems.length > 0 && (
          <ul className="space-y-2">
            {problems.map((check, index) => (
              <CheckLine key={`${check.name}:${index}`} check={check} />
            ))}
          </ul>
        )}
        {fine.length > 0 && (
          <div className="space-y-2">
            <Button variant="ghost" size="sm" onClick={() => setShowOk(!showOk)}>
              {showOk ? t('doctor.hideOk') : t('doctor.showOk', { count: fine.length })}
            </Button>
            {showOk && (
              <ul className="space-y-2">
                {fine.map((check, index) => (
                  <CheckLine key={`${check.name}:${index}`} check={check} />
                ))}
              </ul>
            )}
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline-secondary"
            size="sm"
            disabled={pending}
            loading={ask.isPending}
            onClick={() => void run(false)}
          >
            {t('doctor.run')}
          </Button>
          <Button
            variant="outline-secondary"
            size="sm"
            disabled={pending}
            loading={ask.isPending}
            confirm={t('doctor.runNetwork.confirm')}
            onClick={() => void run(true)}
          >
            {t('doctor.runNetwork.action')}
          </Button>
        </div>
        {ask.isError && <p className="text-xs text-destructive">{ask.error.message}</p>}
      </div>
    </Section>
  )
}
