import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import { FilterBar, TorrentTable } from '@/features/torrents/list'
import {
  formatRate,
  matchesFilter,
  type TorrentFilter,
  type TorrentList,
  type TorrentSummary,
} from '@/features/torrents/shared'
import { useT } from '@/modules/i18n/use-t'
import { Plus } from 'lucide-react'
import { useState } from 'react'

/** How to switch the client on: the owner does it in the config of the box, the panel only says where. */
const OffNotice = ({ reason }: { reason: string | null }) => {
  const t = useT()
  return (
    <Card compact h2={t('torrents.off.title')} size="sm">
      <div className="space-y-3 text-sm">
        <p>{t('torrents.off.description')}</p>
        <ol className="list-decimal space-y-1 pl-5 text-muted-foreground">
          <li className="font-mono text-foreground">{t('torrents.off.step1')}</li>
          <li>{t('torrents.off.step2')}</li>
          <li>{t('torrents.off.step3')}</li>
        </ol>
        {reason && <p className="text-xs text-muted-foreground">{reason}</p>}
      </div>
    </Card>
  )
}

/**
 * The main part of the page: the service switched off, the list empty, or the list itself under its filters and the
 * rates of all the torrents together. The data comes in, the owner's actions go out.
 *
 * @tags torrents
 */
export const TorrentsScreen = ({
  off,
  reason,
  list,
  busyId,
  error,
  onAdd,
  onOpen,
  onToggle,
  onRemove,
}: {
  off: boolean
  reason: string | null
  list: TorrentList | null
  busyId: string | null
  error: string | null
  onAdd: () => void
  onOpen: (torrent: TorrentSummary) => void
  onToggle: (torrent: TorrentSummary) => void
  onRemove: (torrent: TorrentSummary) => void
}) => {
  const t = useT()
  const [filter, setFilter] = useState<TorrentFilter>('all')
  if (off || !list) {
    return <OffNotice reason={reason} />
  }
  if (list.torrents.length === 0) {
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyTitle>{t('torrents.empty.title')}</EmptyTitle>
          <EmptyDescription>{t('torrents.empty.description')}</EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button icon={Plus} onClick={onAdd}>
            {t('torrents.add.open')}
          </Button>
        </EmptyContent>
      </Empty>
    )
  }
  const shown = list.torrents.filter((torrent) => matchesFilter(torrent, filter))
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground tabular-nums">
          {t('torrents.totals', { down: formatRate(list.rate_down), up: formatRate(list.rate_up) })}
        </p>
        <Button size="sm" icon={Plus} onClick={onAdd}>
          {t('torrents.add.open')}
        </Button>
      </div>
      <FilterBar torrents={list.torrents} value={filter} onChange={setFilter} />
      {error && <p className="text-sm text-destructive">{error}</p>}
      {shown.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t('torrents.filter.empty')}</p>
      ) : (
        <TorrentTable torrents={shown} busyId={busyId} onOpen={onOpen} onToggle={onToggle} onRemove={onRemove} />
      )}
    </div>
  )
}
