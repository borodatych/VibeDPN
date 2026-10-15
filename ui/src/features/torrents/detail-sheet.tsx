import { SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Spinner } from '@/components/ui/spinner'
import { torrentDetailQuery, torrentFilesMutation } from '@/features/torrents/api'
import { DetailView, type FilesChange } from '@/features/torrents/detail'
import { useT } from '@/modules/i18n/use-t'
import { useState } from 'react'

/**
 * The body of the sheet of one torrent: follows it while open, and sends the changes of its files to core
 *
 * @tags torrents
 */
export const DetailSheetBody = ({ id, name }: { id: string; name: string }) => {
  const t = useT()
  const query = torrentDetailQuery.useQuery({ id })
  const change = torrentFilesMutation.useMutation()
  const [shownError, setShownError] = useState<string | null>(null)
  const detail = query.data?.detail
  const send = async (files: FilesChange) => {
    setShownError(null)
    try {
      await change.mutateAsync({ id, ...files })
      await torrentDetailQuery.refetchQuery({ id })
    } catch (error) {
      setShownError(error instanceof Error ? error.message : t('torrents.error.unknown'))
    }
  }
  return (
    <>
      <SheetHeader>
        <SheetTitle className="pr-10 break-all">{detail?.name ?? name}</SheetTitle>
        <SheetDescription className="sr-only">{t('torrents.detail.description')}</SheetDescription>
      </SheetHeader>
      <div className="flex-1 overflow-y-auto px-4 pb-6">
        {detail ? (
          <DetailView detail={detail} error={shownError} onFilesChange={(files) => void send(files)} />
        ) : query.data ? (
          <p className="text-sm text-muted-foreground">{t('torrents.detail.gone')}</p>
        ) : (
          <Spinner size="3xl" className="m-auto" />
        )}
      </div>
    </>
  )
}
