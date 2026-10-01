import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { XSelect } from '@/components/ui/select'
import { logsMutation, logsQuery } from '@/features/logs/api'
import { DEFAULT_TAIL, offeredServices, TAIL_CHOICES, type LogsScope } from '@/features/logs/shared'
import { useLanguage, useT } from '@/modules/i18n/use-t'
import { formatDate } from '@/utils/date'
import { useState } from 'react'

/**
 * The last lines of a container's log, for the services of the page's own subject
 *
 * The host reads them (decision 38): only it sees Docker, and it hides share links, tokens and keys Nothing is shown
 * before `vibedpn up` told core the services of the box, or when the page has none
 *
 * @tags logs
 */
export const LogsCard = ({ scope }: { scope: LogsScope }) => {
  const t = useT()
  const language = useLanguage()
  const view = logsQuery.useQuery().data?.logs ?? null
  const ask = logsMutation.useMutation()
  const services = offeredServices(view?.services ?? [], scope)
  const [chosen, setChosen] = useState<string | null>(null)
  const [tail, setTail] = useState<number>(DEFAULT_TAIL)
  if (services.length === 0) {
    return null
  }
  const service = chosen !== null && services.includes(chosen) ? chosen : services[0]!
  const pending = view?.state.pending ?? false
  // the last log read is one for the whole box: a page shows it only for a service of its own
  const report = view?.report && services.includes(view.report.service) ? view.report : null
  const read = async () => {
    await ask.mutateAsync({ service, tail })
    await logsQuery.refetchQuery()
  }
  return (
    <Card
      compact
      h2={t('logs.title')}
      size="sm"
      action={
        <Button
          variant="outline-secondary"
          size="sm"
          disabled={pending}
          loading={ask.isPending}
          aria-label={t('logs.readOne', { service })}
          onClick={() => void read()}
        >
          {t('logs.read')}
        </Button>
      }
    >
      <div className="space-y-3">
        {/* under the header, not beside it: the action of the header would squeeze it into a narrow column */}
        <p className="text-sm text-muted-foreground">{t('logs.description')}</p>
        <div className="flex flex-wrap items-center gap-2">
          {services.length > 1 && (
            <XSelect
              options={services.map((name) => ({ value: name, label: name }))}
              value={service}
              disabled={pending}
              onValueChange={(value) => setChosen(String(value))}
            />
          )}
          <XSelect
            options={TAIL_CHOICES.map((count) => ({ value: count, label: t('logs.lines', { count }) }))}
            value={tail}
            valueType="number"
            disabled={pending}
            onValueChange={(value) => setTail(Number(value))}
          />
        </div>
        {pending && <p className="text-sm text-warning">{t('logs.pending')}</p>}
        {!pending && view?.state.ok === false && (
          <p className="text-sm text-destructive">{t('logs.failed', { message: view.state.message })}</p>
        )}
        {ask.isError && <p className="text-xs text-destructive">{ask.error.message}</p>}
        {report && (
          <div className="space-y-1">
            <p className="text-sm text-muted-foreground">
              {t('logs.summary', {
                service: report.service,
                tail: report.tail,
                time: formatDate(new Date(report.finished_at * 1000), 'date-time-nice', language),
              })}
            </p>
            {report.text ? (
              <pre className="max-h-96 overflow-auto rounded-md bg-muted p-3 font-mono text-xs wrap-break-word whitespace-pre-wrap">
                {report.text}
              </pre>
            ) : (
              <p className="text-sm text-muted-foreground">{t('logs.empty')}</p>
            )}
          </div>
        )}
      </div>
    </Card>
  )
}
