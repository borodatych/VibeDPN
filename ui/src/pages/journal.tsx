import { useHead } from '@unhead/react'
import { Badge } from '@/components/ui/badge'
import { Section } from '@/components/ui/section'
import { XSelect } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { eventListQuery } from '@/features/events/api'
import {
  EVENT_KINDS,
  eventSubject,
  eventText,
  eventTone,
  JOURNAL_PERIODS,
  type BoxEvent,
  type EventKind,
} from '@/features/events/shared'
import { generalLayout } from '@/layouts/general'
import { redirectUnauthorizedPlugin } from '@/modules/auth/plugins'
import type { T } from '@/modules/i18n/base'
import { useLanguage, useT } from '@/modules/i18n/use-t'
import { formatDate } from '@/utils/date'
import { useState } from 'react'

const ALL_KINDS = 'all'
const TONE_BADGE = { ok: 'success', warning: 'warning' } as const

const kindOptions = (t: T) => [
  { value: ALL_KINDS, label: t('journal.kind.all') },
  ...EVENT_KINDS.map((kind) => ({ value: kind, label: t(`journal.kind.${kind}`) })),
]

const periodOptions = (t: T) =>
  JOURNAL_PERIODS.map((period) => ({ value: String(period.hours), label: t(period.label) }))

const EventRow = ({ event }: { event: BoxEvent }) => {
  const t = useT()
  const language = useLanguage()
  const subject = eventSubject(event, t)
  return (
    <TableRow>
      <TableCell className="text-sm whitespace-nowrap">
        {formatDate(new Date(event.time * 1000), 'date-time', language)}
      </TableCell>
      <TableCell>
        <Badge variant={TONE_BADGE[eventTone(event)]}>{t(`journal.kind.${event.kind}`)}</Badge>
      </TableCell>
      <TableCell>
        <div>{subject.title}</div>
        {subject.detail && <div className="font-mono text-xs text-muted-foreground">{subject.detail}</div>}
      </TableCell>
      <TableCell>{eventText(event, t)}</TableCell>
    </TableRow>
  )
}

export const journalPage = generalLayout.lets
  .page('/journal')
  .use(redirectUnauthorizedPlugin)
  .page(() => {
    const t = useT()
    useHead({ title: t('nav.journal') })
    const [kind, setKind] = useState<EventKind | null>(null)
    const [hours, setHours] = useState<number>(JOURNAL_PERIODS[0].hours)
    const journal = eventListQuery.useQuery({ kind, hours }).data
    const events = journal?.events ?? []

    return (
      <Section h1={t('journal.title')} description={t('journal.description')}>
        <div className="flex flex-wrap gap-3">
          <XSelect
            options={kindOptions(t)}
            value={kind ?? ALL_KINDS}
            onValueChange={(value) => setKind(value === ALL_KINDS ? null : (String(value) as EventKind))}
          />
          <XSelect
            options={periodOptions(t)}
            value={String(hours)}
            onValueChange={(value) => setHours(Number(value))}
          />
        </div>
        {events.length === 0 ? (
          <p className="mt-4 text-sm text-muted-foreground">{journal?.reason ?? t('journal.empty')}</p>
        ) : (
          <Table className="mt-4">
            <TableHeader>
              <TableRow>
                <TableHead>{t('journal.column.time')}</TableHead>
                <TableHead>{t('journal.column.kind')}</TableHead>
                <TableHead>{t('journal.column.subject')}</TableHead>
                <TableHead>{t('journal.column.event')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {events.map((event) => (
                <EventRow key={`${event.time}-${event.subject}-${event.action}`} event={event} />
              ))}
            </TableBody>
          </Table>
        )}
      </Section>
    )
  })
