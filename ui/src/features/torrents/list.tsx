import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { humanBytes } from '@/features/node/shared'
import {
  barPercent,
  countByFilter,
  dotted,
  formatEta,
  formatPercent,
  formatRate,
  formatRatio,
  isRunning,
  statusKey,
  statusVariant,
  TORRENT_FILTERS,
  type TorrentFilter,
  type TorrentSummary,
} from '@/features/torrents/shared'
import type { MessageKey } from '@/modules/i18n/base'
import { useT } from '@/modules/i18n/use-t'
import { cn } from '@/utils'
import { Pause, Play, Trash2 } from 'lucide-react'
import { useState } from 'react'

const FILTER_KEYS: Record<TorrentFilter, MessageKey> = {
  all: 'torrents.filter.all',
  downloading: 'torrents.filter.downloading',
  seeding: 'torrents.filter.seeding',
  paused: 'torrents.filter.paused',
  error: 'torrents.filter.error',
}

/**
 * A bar of progress; the track and the fill are palette tokens, and the reader of the screen gets the value
 *
 * @tags torrents
 */
export const ProgressBar = ({ fraction, label, done }: { fraction: number; label: string; done?: boolean }) => (
  <div
    role="progressbar"
    aria-label={label}
    aria-valuemin={0}
    aria-valuemax={100}
    aria-valuenow={barPercent(fraction)}
    className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
  >
    <div
      className={cn('h-full rounded-full', done ? 'bg-success' : 'bg-primary')}
      style={{ width: `${barPercent(fraction)}%` }}
    />
  </div>
)

/** The filters of the list as a row of buttons with the number of torrents behind each; it wraps on a phone, so no
button is cut off. */
export const FilterBar = ({
  torrents,
  value,
  onChange,
}: {
  torrents: readonly TorrentSummary[]
  value: TorrentFilter
  onChange: (filter: TorrentFilter) => void
}) => {
  const t = useT()
  const counts = countByFilter(torrents)
  return (
    <div role="group" aria-label={t('torrents.filter.label')} className="flex flex-wrap gap-2">
      {TORRENT_FILTERS.map((filter) => (
        <Button
          key={filter}
          size="sm"
          variant={filter === value ? 'default' : 'outline-secondary'}
          aria-pressed={filter === value}
          onClick={() => onChange(filter)}
        >
          {dotted(t(FILTER_KEYS[filter]), counts[filter])}
        </Button>
      ))}
    </div>
  )
}

const TorrentRow = ({
  torrent,
  busy,
  onOpen,
  onToggle,
  onRemove,
}: {
  torrent: TorrentSummary
  busy: boolean
  onOpen: (torrent: TorrentSummary) => void
  onToggle: (torrent: TorrentSummary) => void
  onRemove: (torrent: TorrentSummary) => void
}) => {
  const t = useT()
  const running = isRunning(torrent)
  const complete = torrent.progress >= 1
  return (
    <TableRow className="max-md:grid-cols-2" data-torrent={torrent.id}>
      <TableCell className="min-w-0 py-3 max-md:col-span-2 md:w-[34%] md:max-w-0 md:pr-4">
        <button
          type="button"
          className="block max-w-full link text-left font-medium break-words md:truncate"
          title={torrent.name}
          onClick={() => onOpen(torrent)}
        >
          {torrent.name}
        </button>
        <div className="mt-2 flex items-center gap-3">
          <ProgressBar fraction={torrent.progress} label={torrent.name} done={complete} />
          <span className="text-xs whitespace-nowrap text-muted-foreground tabular-nums">
            {formatPercent(torrent.progress)}
          </span>
        </div>
        {torrent.error !== null && <p className="mt-1 text-xs text-destructive">{torrent.error}</p>}
      </TableCell>
      <TableCell data-label={t('torrents.column.status')}>
        <Badge variant={statusVariant(torrent)}>{t(statusKey(torrent))}</Badge>
      </TableCell>
      <TableCell data-label={t('torrents.column.down')} className="tabular-nums md:text-right">
        {formatRate(torrent.rate_down)}
      </TableCell>
      <TableCell data-label={t('torrents.column.up')} className="tabular-nums md:text-right">
        {formatRate(torrent.rate_up)}
      </TableCell>
      <TableCell data-label={t('torrents.column.eta')} className="tabular-nums md:text-right">
        {formatEta(torrent.eta, t)}
      </TableCell>
      <TableCell data-label={t('torrents.column.size')} className="tabular-nums md:text-right">
        {humanBytes(torrent.size)}
      </TableCell>
      <TableCell data-label={t('torrents.column.ratio')} className="tabular-nums md:text-right">
        {formatRatio(torrent.ratio)}
      </TableCell>
      <TableCell className="max-md:col-span-2">
        <div className="flex gap-1 md:justify-end">
          <Button
            variant="outline-secondary"
            size="sm"
            icon={running ? Pause : Play}
            loading={busy}
            onClick={() => onToggle(torrent)}
          >
            <span className="md:sr-only">{running ? t('torrents.stop') : t('torrents.start')}</span>
          </Button>
          <Button variant="ghost" size="sm" icon={Trash2} disabled={busy} onClick={() => onRemove(torrent)}>
            <span className="md:sr-only">{t('torrents.remove')}</span>
          </Button>
        </div>
      </TableCell>
    </TableRow>
  )
}

/**
 * The torrents as one table: wide on a laptop, a pile of cards on a phone (`table-stack`), the controls the same
 *
 * @tags torrents
 */
export const TorrentTable = ({
  torrents,
  busyId,
  onOpen,
  onToggle,
  onRemove,
}: {
  torrents: readonly TorrentSummary[]
  busyId: string | null
  onOpen: (torrent: TorrentSummary) => void
  onToggle: (torrent: TorrentSummary) => void
  onRemove: (torrent: TorrentSummary) => void
}) => {
  const t = useT()
  return (
    <Table className="table-stack">
      <TableHeader>
        <TableRow>
          <TableHead>{t('torrents.column.name')}</TableHead>
          <TableHead>{t('torrents.column.status')}</TableHead>
          <TableHead className="text-right">{t('torrents.column.down')}</TableHead>
          <TableHead className="text-right">{t('torrents.column.up')}</TableHead>
          <TableHead className="text-right">{t('torrents.column.eta')}</TableHead>
          <TableHead className="text-right">{t('torrents.column.size')}</TableHead>
          <TableHead className="text-right">{t('torrents.column.ratio')}</TableHead>
          <TableHead />
        </TableRow>
      </TableHeader>
      <TableBody>
        {torrents.map((torrent) => (
          <TorrentRow
            key={torrent.id}
            torrent={torrent}
            busy={busyId === torrent.id}
            onOpen={onOpen}
            onToggle={onToggle}
            onRemove={onRemove}
          />
        ))}
      </TableBody>
    </Table>
  )
}

type RemoveProps = {
  torrent: TorrentSummary | null
  pending: boolean
  error: string | null
  onConfirm: (deleteData: boolean) => void
  onCancel: () => void
}

// Inside the content of the dialog: it unmounts on close, so the next torrent starts with the files kept again
const RemoveForm = ({ torrent, pending, error, onConfirm, onCancel }: RemoveProps) => {
  const t = useT()
  const [deleteData, setDeleteData] = useState(false)
  return (
    <>
      <DialogHeader>
        <DialogTitle>{t('torrents.remove.title')}</DialogTitle>
        <DialogDescription className="break-all">{torrent?.name}</DialogDescription>
      </DialogHeader>
      <label className="flex items-start gap-2 text-sm">
        <Checkbox
          className="mt-0.5"
          checked={deleteData}
          onCheckedChange={(checked) => setDeleteData(checked === true)}
        />
        <span>
          {t('torrents.remove.data')}
          <span className="block text-xs text-muted-foreground">{t('torrents.remove.dataHint')}</span>
        </span>
      </label>
      {error && <p className="text-sm text-destructive">{error}</p>}
      <DialogFooter>
        <Button variant="outline-secondary" onClick={onCancel}>
          {t('common.cancel')}
        </Button>
        <Button variant="destructive" loading={pending} onClick={() => onConfirm(deleteData)}>
          {deleteData ? t('torrents.remove.withData') : t('torrents.remove.keepData')}
        </Button>
      </DialogFooter>
    </>
  )
}

/**
 * Asks before a torrent goes, and whether its files go with it; the choice starts at «keep the files»
 *
 * @tags torrents
 */
export const RemoveDialog = (props: RemoveProps) => (
  <Dialog open={props.torrent !== null} onOpenChange={(open) => !open && props.onCancel()}>
    <DialogContent>
      <RemoveForm {...props} />
    </DialogContent>
  </Dialog>
)
