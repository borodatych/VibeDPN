import { useHead } from '@unhead/react'
import { PageTitle } from '@/components/blocks/page-title'
import { Sheet, SheetContent } from '@/components/ui/sheet'
import { Sections } from '@/components/ui/section'
import { AddDialog } from '@/features/torrents/add-dialog'
import { DetailSheetBody } from '@/features/torrents/detail-sheet'
import { RemoveDialog } from '@/features/torrents/list'
import { SpeedCard, StorageCard, type SpeedChange } from '@/features/torrents/panels'
import { TorrentsScreen } from '@/features/torrents/screen'
import {
  speedSessionMutation,
  speedSessionQuery,
  storageChooseMutation,
  storageQuery,
  storageRefreshMutation,
  torrentRemoveMutation,
  torrentsQuery,
  torrentStartMutation,
  torrentStopMutation,
} from '@/features/torrents/api'
import { isRunning, type TorrentSummary } from '@/features/torrents/shared'
import { generalLayout } from '@/layouts/general'
import { redirectUnauthorizedPlugin } from '@/modules/auth/plugins'
import { useT } from '@/modules/i18n/use-t'
import { useState } from 'react'

const SpeedSection = () => {
  const session = speedSessionQuery.useQuery().data?.session
  const save = speedSessionMutation.useMutation()
  if (!session) {
    return null
  }
  const apply = async (change: SpeedChange) => {
    await save.mutateAsync(change).catch(() => null)
    await speedSessionQuery.refetchQuery()
  }
  return (
    <SpeedCard
      // a fresh form after the saved limits come back: the fields start from what core holds
      key={`${session.speed_limit_down_enabled}-${session.speed_limit_down}-${session.speed_limit_up_enabled}-${session.speed_limit_up}`}
      session={session}
      pending={save.isPending}
      error={save.isError ? save.error.message : null}
      saved={save.isSuccess}
      onSave={(change) => void apply(change)}
    />
  )
}

const StorageSection = () => {
  const storage = storageQuery.useQuery().data?.storage
  const choose = storageChooseMutation.useMutation()
  const refresh = storageRefreshMutation.useMutation()
  if (!storage) {
    return null
  }
  const run = async (action: () => Promise<unknown>) => {
    await action().catch(() => null)
    await storageQuery.refetchQuery()
  }
  return (
    <StorageCard
      storage={storage}
      choosing={choose.isPending}
      refreshing={refresh.isPending}
      error={choose.isError ? choose.error.message : refresh.isError ? refresh.error.message : null}
      onChoose={(uuid) => void run(async () => await choose.mutateAsync({ uuid }))}
      onRefresh={() => void run(async () => await refresh.mutateAsync(undefined))}
    />
  )
}

export const torrentsPage = generalLayout.lets
  .page('/torrents')
  .use(redirectUnauthorizedPlugin)
  .page(() => {
    const t = useT()
    useHead({ title: t('nav.torrents') })
    const answer = torrentsQuery.useQuery().data
    const start = torrentStartMutation.useMutation()
    const stop = torrentStopMutation.useMutation()
    const remove = torrentRemoveMutation.useMutation()
    const [addOpen, setAddOpen] = useState(false)
    const [opened, setOpened] = useState<TorrentSummary | null>(null)
    const [removing, setRemoving] = useState<TorrentSummary | null>(null)
    const [busyId, setBusyId] = useState<string | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [notice, setNotice] = useState<string | null>(null)

    const toggle = async (torrent: TorrentSummary) => {
      setBusyId(torrent.id)
      setError(null)
      try {
        await (isRunning(torrent) ? stop : start).mutateAsync({ id: torrent.id })
        await torrentsQuery.refetchQuery()
      } catch (failure) {
        setError(failure instanceof Error ? failure.message : t('torrents.error.unknown'))
      } finally {
        setBusyId(null)
      }
    }
    const drop = async (deleteData: boolean) => {
      if (!removing) {
        return
      }
      const done = await remove.mutateAsync({ id: removing.id, data: deleteData }).catch(() => null)
      if (done) {
        setRemoving(null)
        setOpened((current) => (current?.id === done.id ? null : current))
        await torrentsQuery.refetchQuery()
      }
    }

    return (
      <Sections gap="lg">
        <PageTitle title={t('torrents.title')} description={t('torrents.description')} />
        {notice && <p className="text-sm text-muted-foreground">{notice}</p>}
        <TorrentsScreen
          off={answer?.off ?? false}
          reason={answer?.reason ?? null}
          list={answer?.list ?? null}
          busyId={busyId}
          error={error}
          onAdd={() => setAddOpen(true)}
          onOpen={setOpened}
          onToggle={(torrent) => void toggle(torrent)}
          onRemove={(torrent) => {
            remove.reset()
            setRemoving(torrent)
          }}
        />
        {answer && !answer.off && (
          <div className="grid items-start gap-6 lg:grid-cols-2">
            <SpeedSection />
            <StorageSection />
          </div>
        )}
        <AddDialog
          open={addOpen}
          onOpenChange={setAddOpen}
          onAdded={(torrent, duplicate) =>
            setNotice(t(duplicate ? 'torrents.add.duplicate' : 'torrents.add.added', { name: torrent.name }))
          }
        />
        <RemoveDialog
          torrent={removing}
          pending={remove.isPending}
          error={remove.isError ? remove.error.message : null}
          onConfirm={(deleteData) => void drop(deleteData)}
          onCancel={() => setRemoving(null)}
        />
        <Sheet open={opened !== null} onOpenChange={(open) => !open && setOpened(null)}>
          <SheetContent className="data-[side=right]:w-full data-[side=right]:sm:max-w-3xl">
            {opened && <DetailSheetBody key={opened.id} id={opened.id} name={opened.name} />}
          </SheetContent>
        </Sheet>
      </Sections>
    )
  })
