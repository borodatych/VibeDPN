import type { ApplyView } from '@/features/uplinks/shared'
import { useLanguage, useT } from '@/modules/i18n/use-t'
import { formatDate } from '@/utils/date'

/**
 * Where the host is with the last change the panel asked for: waiting, failed with its reason, or applied at a time.
 *
 * @tags uplinks, access
 */
export const ApplyLine = ({ apply }: { apply: ApplyView }) => {
  const t = useT()
  const language = useLanguage()
  if (apply.pending) {
    return <p className="text-sm text-warning">{t('uplinks.apply.pending')}</p>
  }
  if (apply.ok === false) {
    return <p className="text-sm text-destructive">{t('uplinks.apply.failed', { message: apply.message })}</p>
  }
  if (apply.ok && apply.finished_at !== null) {
    const time = formatDate(new Date(apply.finished_at * 1000), 'date-time-nice', language)
    return <p className="text-sm text-muted-foreground">{t('uplinks.apply.ok', { time })}</p>
  }
  return null
}
