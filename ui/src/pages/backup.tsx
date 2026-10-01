import { useHead } from '@unhead/react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Section, Sections } from '@/components/ui/section'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { backupMutation, backupsQuery, deleteArchiveMutation, restoreArchiveMutation } from '@/features/backup/api'
import {
  archiveUrl,
  busyWithArchives,
  MAX_RESTORE_BYTES,
  RESTORE_UPLOAD_URL,
  uploadProblem,
  type Archive,
} from '@/features/backup/shared'
import { humanBytes } from '@/features/node/shared'
import type { ApplyView } from '@/features/uplinks/shared'
import { generalLayout } from '@/layouts/general'
import { redirectUnauthorizedPlugin } from '@/modules/auth/plugins'
import { useLanguage, useT } from '@/modules/i18n/use-t'
import { formatDate } from '@/utils/date'
import { useState } from 'react'

const refresh = async () => {
  await backupsQuery.refetchQuery()
}

/** How the last backup or restore the panel asked for went: waiting for the host, failed, or done. */
const TaskLine = ({ task, kind }: { task: ApplyView; kind: 'backup' | 'restore' }) => {
  const t = useT()
  const language = useLanguage()
  if (task.pending) {
    return <p className="text-sm text-warning">{t(`backup.${kind}.pending`)}</p>
  }
  if (task.ok === false) {
    return <p className="text-sm text-destructive">{t(`backup.${kind}.failed`, { message: task.message })}</p>
  }
  if (task.ok && task.finished_at !== null) {
    const time = formatDate(new Date(task.finished_at * 1000), 'date-time-nice', language)
    return <p className="text-sm text-muted-foreground">{t(`backup.${kind}.done`, { time, message: task.message })}</p>
  }
  return null
}

const ArchiveRow = ({ archive, busy }: { archive: Archive; busy: boolean }) => {
  const t = useT()
  const language = useLanguage()
  const restore = restoreArchiveMutation.useMutation()
  const remove = deleteArchiveMutation.useMutation()
  const act = async (run: () => Promise<unknown>) => {
    await run()
    await refresh()
  }
  return (
    <TableRow>
      {/* the actions under the name, not in a column of their own: three buttons do not fit a phone beside it */}
      <TableCell className="whitespace-normal">
        <div>{formatDate(new Date(archive.created_at * 1000), 'date-time-nice', language)}</div>
        <div className="font-mono text-xs break-all text-muted-foreground">{archive.name}</div>
        <div className="mt-2 flex flex-wrap gap-2">
          <Button asChild variant="outline-secondary" size="sm">
            <a href={archiveUrl(archive.name)} download={archive.name}>
              {t('backup.download')}
            </a>
          </Button>
          <Button
            variant="outline-secondary"
            size="sm"
            disabled={busy}
            loading={restore.isPending}
            confirm={t('backup.restore.confirm')}
            onClick={() => void act(async () => await restore.mutateAsync({ name: archive.name }))}
          >
            {t('backup.restore.action')}
          </Button>
          <Button
            variant="outline-secondary"
            size="sm"
            disabled={busy}
            loading={remove.isPending}
            confirm={t('backup.delete.confirm')}
            onClick={() => void act(async () => await remove.mutateAsync({ name: archive.name }))}
          >
            {t('backup.delete.action')}
          </Button>
        </div>
        {restore.isError && <p className="mt-1 text-xs text-destructive">{restore.error.message}</p>}
        {remove.isError && <p className="mt-1 text-xs text-destructive">{remove.error.message}</p>}
      </TableCell>
      <TableCell className="align-top whitespace-nowrap">{humanBytes(archive.size)}</TableCell>
    </TableRow>
  )
}

/** A file of the owner's sent for a restore: it goes to core as it is, through the session of the panel. */
const UploadForm = ({ busy }: { busy: boolean }) => {
  const t = useT()
  const [file, setFile] = useState<File | null>(null)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const problem = file ? uploadProblem(file) : null
  const send = async () => {
    if (!file) {
      return
    }
    setSending(true)
    setError(null)
    try {
      const response = await fetch(RESTORE_UPLOAD_URL, { method: 'PUT', body: file })
      if (!response.ok) {
        const body: unknown = await response.json().catch(() => null)
        const detail =
          body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string'
            ? body.detail
            : `HTTP ${response.status}`
        setError(detail)
        return
      }
      setFile(null)
      await refresh()
    } finally {
      setSending(false)
    }
  }
  return (
    <div className="space-y-2">
      <p className="font-accent text-sm text-muted-foreground">{t('backup.upload.title')}</p>
      <Input
        type="file"
        accept=".tar.gz,.gz,application/gzip"
        className="max-w-sm"
        disabled={busy}
        onChange={(event) => setFile(event.target.files?.[0] ?? null)}
      />
      <p className="text-xs text-muted-foreground">{t('backup.upload.hint', { max: humanBytes(MAX_RESTORE_BYTES) })}</p>
      <Button
        variant="outline-secondary"
        size="sm"
        disabled={busy || !file || problem !== null}
        loading={sending}
        confirm={t('backup.restore.confirm')}
        onClick={() => void send()}
      >
        {t('backup.upload.action')}
      </Button>
      {problem && (
        <p className="text-sm text-destructive">
          {t(`backup.upload.problem.${problem}`, { max: humanBytes(MAX_RESTORE_BYTES) })}
        </p>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  )
}

export const backupPage = generalLayout.lets
  .page('/backup')
  .use(redirectUnauthorizedPlugin)
  .page(() => {
    const t = useT()
    useHead({ title: t('nav.backup') })
    const query = backupsQuery.useQuery()
    const make = backupMutation.useMutation()
    const view = query.data?.backups ?? null
    const away = query.data?.away ?? false
    const busy = away || (view !== null && busyWithArchives(view))
    const ask = async () => {
      await make.mutateAsync({})
      await refresh()
    }
    return (
      <Sections gap="lg">
        <Section h1={t('backup.title')} description={t('backup.description', { keep: view?.keep ?? '' })}>
          <div className="space-y-3">
            {away && <p className="text-sm text-warning">{t('backup.away')}</p>}
            {view && <TaskLine task={view.backup} kind="backup" />}
            {view && <TaskLine task={view.restore} kind="restore" />}
            <div>
              <Button
                disabled={busy}
                loading={make.isPending}
                confirm={t('backup.make.confirm')}
                onClick={() => void ask()}
              >
                {t('backup.make.action')}
              </Button>
            </div>
            {make.isError && <p className="text-sm text-destructive">{make.error.message}</p>}
          </div>
        </Section>
        <Section h2={t('backup.list.title')}>
          {view === null || view.archives.length === 0 ? (
            <p className="text-sm text-muted-foreground">{away ? t('backup.away') : t('backup.list.empty')}</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('backup.list.made')}</TableHead>
                  <TableHead>{t('backup.list.size')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {view.archives.map((archive) => (
                  <ArchiveRow key={archive.name} archive={archive} busy={busy} />
                ))}
              </TableBody>
            </Table>
          )}
        </Section>
        <Section h2={t('backup.restore.title')} description={t('backup.restore.description')}>
          <UploadForm busy={busy} />
        </Section>
      </Sections>
    )
  })
