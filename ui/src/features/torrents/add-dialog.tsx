import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { AddForm, type AddPayload } from '@/features/torrents/add'
import { torrentAddMutation, torrentsQuery } from '@/features/torrents/api'
import type { TorrentSummary } from '@/features/torrents/shared'
import { useT } from '@/modules/i18n/use-t'

/**
 * The dialog that adds a torrent: sends the form to core, closes on success and tells when the torrent was there
 * already
 *
 * @tags torrents
 */
export const AddDialog = ({
  open,
  onOpenChange,
  onAdded,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onAdded: (torrent: Pick<TorrentSummary, 'id' | 'name'>, duplicate: boolean) => void
}) => {
  const t = useT()
  const add = torrentAddMutation.useMutation()
  const submit = async (payload: AddPayload) => {
    const answer = await add.mutateAsync(payload).catch(() => null)
    if (answer) {
      await torrentsQuery.refetchQuery()
      onOpenChange(false)
      onAdded(answer, answer.duplicate)
    }
  }
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          add.reset()
        }
        onOpenChange(next)
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('torrents.add.title')}</DialogTitle>
          <DialogDescription>{t('torrents.add.description')}</DialogDescription>
        </DialogHeader>
        <AddForm
          pending={add.isPending}
          error={add.isError ? add.error.message : null}
          onSubmit={(payload) => void submit(payload)}
        />
      </DialogContent>
    </Dialog>
  )
}
