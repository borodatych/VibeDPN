import { Button } from '@/components/ui/button'
import { Section } from '@/components/ui/section'
import { updateMutation, updateQuery } from '@/features/update/api'
import { updatedSince, type UpdateResult } from '@/features/update/shared'
import type { T } from '@/modules/i18n/base'
import { useLanguage, useT } from '@/modules/i18n/use-t'
import { formatDate } from '@/utils/date'
import { useEffect, useState } from 'react'

const resultLine = (last: UpdateResult, t: T, time: string) => {
  if (!last.ok) {
    return <p className="text-sm text-destructive">{t('update.failed', { message: last.message })}</p>
  }
  if (last.before !== '' && last.before === last.after) {
    return <p className="text-sm text-muted-foreground">{t('update.latest', { commit: last.after, time })}</p>
  }
  return (
    <p className="text-sm text-muted-foreground">
      {t('update.done', { before: last.before, after: last.after, time })}
    </p>
  )
}

/**
 * The update of the box from the panel: the version it runs, the button, and how the last update ended
 *
 * The host runs the update (decision 26): the box restarts, and core and the panel with it
 *
 * Once the update asked here has finished well, the page reloads — the browser still runs the old version
 *
 * @tags update
 */
export const UpdateCard = () => {
  const t = useT()
  const language = useLanguage()
  const query = updateQuery.useQuery()
  const mutation = updateMutation.useMutation()
  const [askedAt, setAskedAt] = useState<number | null>(null)
  const view = query.data?.update ?? null
  const restarting = query.data?.restarting ?? false
  useEffect(() => {
    if (askedAt !== null && view !== null && updatedSince(view, askedAt)) {
      window.location.reload()
    }
  }, [askedAt, view])
  const ask = async () => {
    setAskedAt(Date.now() / 1000)
    await mutation.mutateAsync({})
    await updateQuery.refetchQuery()
  }
  const busy = restarting || (view?.pending ?? false)
  return (
    <Section h2={t('update.title')} description={t('update.description')}>
      <div className="flex flex-col gap-3">
        <p className="text-sm">
          {view?.commit && view.branch
            ? t('update.version', {
                branch: view.branch,
                commit: view.commit,
                date: view.committed_at ? formatDate(new Date(view.committed_at), 'date-time-nice', language) : '',
              })
            : t('update.versionUnknown')}
        </p>
        {restarting && <p className="text-sm text-warning">{t('update.restarting')}</p>}
        {!restarting && view?.pending && <p className="text-sm text-warning">{t('update.pending')}</p>}
        {!busy &&
          view?.last &&
          resultLine(view.last, t, formatDate(new Date(view.last.finished_at * 1000), 'date-time-nice', language))}
        <div>
          <Button
            variant="outline-secondary"
            size="sm"
            loading={mutation.isPending}
            disabled={busy}
            confirm={t('update.confirm')}
            onClick={() => void ask()}
          >
            {t('update.action')}
          </Button>
        </div>
        {mutation.isError && <p className="text-xs text-destructive">{mutation.error.message}</p>}
      </div>
    </Section>
  )
}
