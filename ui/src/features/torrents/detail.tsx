import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { XSelect } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ProgressBar } from '@/features/torrents/list'
import { humanBytes } from '@/features/node/shared'
import {
  dotted,
  fileFraction,
  FILE_PRIORITIES,
  formatCount,
  formatEta,
  formatPercent,
  formatRate,
  formatRatio,
  statusKey,
  statusVariant,
  type FilePriority,
  type TorrentDetail,
} from '@/features/torrents/shared'
import type { MessageKey } from '@/modules/i18n/base'
import { useLanguage, useT } from '@/modules/i18n/use-t'
import { formatDate } from '@/utils/date'

const PRIORITY_KEYS: Record<FilePriority, MessageKey> = {
  low: 'torrents.priority.low',
  normal: 'torrents.priority.normal',
  high: 'torrents.priority.high',
}

/** What the owner changes in the files: the indices it applies to and the one or two things set on them. */
export type FilesChange = { indices: number[]; wanted: boolean | null; priority: FilePriority | null }

const Fact = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <div className="min-w-0">
    <dt className="text-xs text-muted-foreground">{label}</dt>
    <dd className="text-sm break-words tabular-nums">{children}</dd>
  </div>
)

const FilesTab = ({ detail, onChange }: { detail: TorrentDetail; onChange: (change: FilesChange) => void }) => {
  const t = useT()
  const priorityOptions = FILE_PRIORITIES.map((value) => ({ value, label: t(PRIORITY_KEYS[value]) }))
  if (detail.files.length === 0) {
    return <p className="text-sm text-muted-foreground">{t('torrents.files.empty')}</p>
  }
  const allWanted = detail.files.every((file) => file.wanted)
  return (
    <div className="space-y-3">
      <label className="flex items-center gap-2 text-sm">
        <Checkbox
          checked={allWanted}
          onCheckedChange={(checked) =>
            onChange({ indices: detail.files.map((file) => file.index), wanted: checked === true, priority: null })
          }
        />
        {t('torrents.files.all')}
      </label>
      <Table className="table-stack">
        <TableHeader>
          <TableRow>
            <TableHead>{t('torrents.files.name')}</TableHead>
            <TableHead className="text-right">{t('torrents.column.size')}</TableHead>
            <TableHead className="text-right">{t('torrents.files.done')}</TableHead>
            <TableHead>{t('torrents.files.priority')}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {detail.files.map((file) => (
            <TableRow key={file.index} className="max-md:grid-cols-2">
              <TableCell className="min-w-0 py-2 max-md:col-span-2">
                <label className="flex items-start gap-2">
                  <Checkbox
                    className="mt-0.5"
                    checked={file.wanted}
                    onCheckedChange={(checked) =>
                      onChange({ indices: [file.index], wanted: checked === true, priority: null })
                    }
                  />
                  <span className="min-w-0 text-sm break-all">{file.name}</span>
                </label>
              </TableCell>
              <TableCell data-label={t('torrents.column.size')} className="tabular-nums md:text-right">
                {humanBytes(file.size)}
              </TableCell>
              <TableCell data-label={t('torrents.files.done')} className="tabular-nums md:text-right">
                {formatPercent(fileFraction(file))}
              </TableCell>
              <TableCell className="max-md:col-span-2">
                <XSelect
                  options={priorityOptions}
                  value={file.priority}
                  triggerProps={{ size: 'sm', 'aria-label': t('torrents.files.priority') }}
                  onValueChange={(value) => {
                    const priority = FILE_PRIORITIES.find((candidate) => candidate === value)
                    if (priority) {
                      onChange({ indices: [file.index], wanted: null, priority })
                    }
                  }}
                />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

const PeersTab = ({ detail }: { detail: TorrentDetail }) => {
  const t = useT()
  if (detail.peers.length === 0) {
    return <p className="text-sm text-muted-foreground">{t('torrents.peers.empty')}</p>
  }
  return (
    <Table className="table-stack">
      <TableHeader>
        <TableRow>
          <TableHead>{t('torrents.peers.address')}</TableHead>
          <TableHead>{t('torrents.peers.client')}</TableHead>
          <TableHead className="text-right">{t('torrents.files.done')}</TableHead>
          <TableHead className="text-right">{t('torrents.column.down')}</TableHead>
          <TableHead className="text-right">{t('torrents.column.up')}</TableHead>
          <TableHead>{t('torrents.peers.flags')}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {detail.peers.map((peer) => (
          <TableRow key={`${peer.address}-${peer.client}`} className="max-md:grid-cols-2">
            <TableCell className="font-mono text-xs max-md:col-span-2">{peer.address}</TableCell>
            <TableCell data-label={t('torrents.peers.client')} className="break-words">
              {peer.client}
            </TableCell>
            <TableCell data-label={t('torrents.files.done')} className="tabular-nums md:text-right">
              {formatPercent(peer.progress)}
            </TableCell>
            <TableCell data-label={t('torrents.column.down')} className="tabular-nums md:text-right">
              {formatRate(peer.rate_down)}
            </TableCell>
            <TableCell data-label={t('torrents.column.up')} className="tabular-nums md:text-right">
              {formatRate(peer.rate_up)}
            </TableCell>
            <TableCell data-label={t('torrents.peers.flags')} className="font-mono text-xs">
              {peer.flags}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

const TrackersTab = ({ detail }: { detail: TorrentDetail }) => {
  const t = useT()
  const language = useLanguage()
  if (detail.trackers.length === 0) {
    return <p className="text-sm text-muted-foreground">{t('torrents.trackers.empty')}</p>
  }
  return (
    <Table className="table-stack">
      <TableHeader>
        <TableRow>
          <TableHead>{t('torrents.trackers.host')}</TableHead>
          <TableHead className="text-right">{t('torrents.trackers.seeders')}</TableHead>
          <TableHead className="text-right">{t('torrents.trackers.leechers')}</TableHead>
          <TableHead>{t('torrents.trackers.last')}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {detail.trackers.map((tracker) => (
          <TableRow key={tracker.announce} className="max-md:grid-cols-2">
            <TableCell className="break-all max-md:col-span-2" title={tracker.announce}>
              {tracker.host}
            </TableCell>
            <TableCell data-label={t('torrents.trackers.seeders')} className="tabular-nums md:text-right">
              {formatCount(tracker.seeders)}
            </TableCell>
            <TableCell data-label={t('torrents.trackers.leechers')} className="tabular-nums md:text-right">
              {formatCount(tracker.leechers)}
            </TableCell>
            <TableCell data-label={t('torrents.trackers.last')} className="max-md:col-span-2">
              <span className={tracker.last_announce_ok ? 'text-muted-foreground' : 'text-destructive'}>
                {tracker.last_announce_result || t('common.none')}
              </span>
              {tracker.last_announce_time ? (
                <span className="block text-xs text-muted-foreground">
                  {formatDate(new Date(tracker.last_announce_time * 1000), 'date-time-nice', language)}
                </span>
              ) : null}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

/**
 * One torrent opened: what it is made of and who it talks to. Pure: the data comes in, the changes go out
 *
 * @tags torrents
 */
export const DetailView = ({
  detail,
  error,
  onFilesChange,
}: {
  detail: TorrentDetail
  error?: string | null
  onFilesChange: (change: FilesChange) => void
}) => {
  const t = useT()
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <div className="flex items-center gap-3">
          <Badge variant={statusVariant(detail)}>{t(statusKey(detail))}</Badge>
          <span className="text-sm tabular-nums">{formatPercent(detail.progress)}</span>
        </div>
        <ProgressBar fraction={detail.progress} label={detail.name} done={detail.progress >= 1} />
        {detail.error !== null && <p className="text-sm text-destructive">{detail.error}</p>}
      </div>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Fact label={t('torrents.column.size')}>{humanBytes(detail.size)}</Fact>
        <Fact label={t('torrents.column.down')}>{formatRate(detail.rate_down)}</Fact>
        <Fact label={t('torrents.column.up')}>{formatRate(detail.rate_up)}</Fact>
        <Fact label={t('torrents.column.eta')}>{formatEta(detail.eta, t)}</Fact>
        <Fact label={t('torrents.column.ratio')}>{formatRatio(detail.ratio)}</Fact>
        <Fact label={t('torrents.detail.folder')}>{detail.download_dir}</Fact>
      </dl>
      {error && <p className="text-sm text-destructive">{error}</p>}
      <Tabs defaultValue="files">
        <TabsList className="max-w-full overflow-x-auto">
          <TabsTrigger value="files">{dotted(t('torrents.tab.files'), detail.files.length)}</TabsTrigger>
          <TabsTrigger value="peers">{dotted(t('torrents.tab.peers'), detail.peers.length)}</TabsTrigger>
          <TabsTrigger value="trackers">{dotted(t('torrents.tab.trackers'), detail.trackers.length)}</TabsTrigger>
        </TabsList>
        <TabsContent value="files">
          <FilesTab detail={detail} onChange={onFilesChange} />
        </TabsContent>
        <TabsContent value="peers">
          <PeersTab detail={detail} />
        </TabsContent>
        <TabsContent value="trackers">
          <TrackersTab detail={detail} />
        </TabsContent>
      </Tabs>
    </div>
  )
}
