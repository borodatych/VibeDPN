import { useHead } from '@unhead/react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ListDetail } from '@/components/blocks/list-detail'
import { PageTitle } from '@/components/blocks/page-title'
import { Card } from '@/components/ui/card'
import { Sections } from '@/components/ui/section'
import { XSwitch } from '@/components/ui/switch'
import { qrImageSource } from '@/features/access/shared'
import { humanBytes } from '@/features/node/shared'
import { LogsCard } from '@/features/logs/card'
import {
  peerAddMutation,
  peerFileMutation,
  peerRemoveMutation,
  peerTrafficQuery,
  peersQuery,
} from '@/features/peers/api'
import {
  ADD_PEER,
  pickPeer,
  PEER_NAME,
  TRAFFIC_DAYS,
  peerFileName,
  peerLinkState,
  type Peer,
  type PeerFile,
  type PeerLinkState,
  type PeerTraffic,
} from '@/features/peers/shared'
import { generalLayout } from '@/layouts/general'
import { redirectUnauthorizedPlugin } from '@/modules/auth/plugins'
import type { MessageKey } from '@/modules/i18n/base'
import { useLanguage, useT } from '@/modules/i18n/use-t'
import { formatDate } from '@/utils/date'
import { useState } from 'react'
import { z } from 'zod'

// Sample value for the empty name field: data in the form the field takes, the same in every language
const EXAMPLE_PEER = 'dacha'
const MS_PER_SECOND = 1000

const STATE_KEYS: Record<PeerLinkState, MessageKey> = {
  unknown: 'peers.state.unknown',
  pending: 'peers.state.pending',
  never: 'peers.state.never',
  online: 'peers.state.online',
  offline: 'peers.state.offline',
}
const STATE_BADGES = {
  unknown: 'secondary',
  pending: 'warning',
  never: 'secondary',
  online: 'success',
  offline: 'warning',
} as const

/** Hand the file over as a download: the browser saves it, nothing is kept by the panel. */
const download = (file: PeerFile) => {
  const url = URL.createObjectURL(new Blob([file.config], { type: 'text/plain' }))
  const link = document.createElement('a')
  link.href = url
  link.download = peerFileName(file.name)
  link.click()
  URL.revokeObjectURL(url)
}

const FileCard = ({ file, onClose }: { file: PeerFile; onClose: () => void }) => {
  const t = useT()
  return (
    <div className="space-y-3 rounded-md border p-4 text-sm">
      <p className="font-semibold">{t('peers.file.title', { name: file.name })}</p>
      {file.qr_svg && (
        <img
          src={qrImageSource(file.qr_svg)}
          alt={t('peers.file.qrAlt', { name: file.name })}
          className="size-64 max-w-full"
        />
      )}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" onClick={() => download(file)}>
          {t('peers.file.download', { file: peerFileName(file.name) })}
        </Button>
        <Button size="sm" variant="ghost" onClick={onClose}>
          {t('peers.file.hide')}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">{t('peers.file.warning')}</p>
      <p className="text-xs text-muted-foreground">{t('peers.file.home')}</p>
      <p className="text-xs text-muted-foreground">{t('peers.file.phone')}</p>
    </div>
  )
}

/** The chosen peer: how it is linked, what it carried, its file, and its removal in the header */
const PeerDetail = ({
  peer,
  checkedAt,
  total,
  file,
  onFile,
  onRemoved,
}: {
  peer: Peer
  checkedAt: number
  total: PeerTraffic | undefined
  file: PeerFile | null
  onFile: (file: PeerFile | null) => void
  onRemoved: () => void
}) => {
  const t = useT()
  const language = useLanguage()
  const fetchFile = peerFileMutation.useMutation()
  const remove = peerRemoveMutation.useMutation()
  const state = peerLinkState(peer, checkedAt)
  const showFile = async () => {
    onFile((await fetchFile.mutateAsync({ name: peer.name })).file)
  }
  const drop = async () => {
    await remove.mutateAsync({ name: peer.name })
    onRemoved()
    await peersQuery.refetchQuery()
  }
  return (
    <Card
      compact
      h2={peer.name}
      size="sm"
      action={
        <Button
          variant="outline-secondary"
          size="sm"
          loading={remove.isPending}
          confirm={t('peers.confirmRemove', { name: peer.name })}
          onClick={() => void drop()}
        >
          {t('common.remove')}
        </Button>
      }
    >
      <div className="space-y-4 text-sm">
        {peer.tunnel_only && <p className="text-muted-foreground">{t('peers.tunnelOnly')}</p>}
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 font-accent">
          <dt className="text-muted-foreground">{t('peers.column.address')}</dt>
          <dd className="font-mono text-xs">{peer.address}</dd>
          <dt className="text-muted-foreground">{t('peers.column.state')}</dt>
          <dd>
            <Badge variant={STATE_BADGES[state]}>{t(STATE_KEYS[state])}</Badge>
            {peer.latest_handshake ? (
              <span className="ml-2 text-xs text-muted-foreground">
                {formatDate(new Date(peer.latest_handshake * MS_PER_SECOND), 'date-time', language)}
              </span>
            ) : null}
          </dd>
          <dt className="text-muted-foreground">{t('peers.column.traffic', { days: TRAFFIC_DAYS })}</dt>
          <dd>
            {total
              ? t('peers.traffic', { rx: humanBytes(total.rx_bytes), tx: humanBytes(total.tx_bytes) })
              : t('common.none')}
          </dd>
        </dl>
        {file?.name === peer.name ? (
          <FileCard file={file} onClose={() => onFile(null)} />
        ) : (
          <Button variant="outline-secondary" size="sm" loading={fetchFile.isPending} onClick={() => void showFile()}>
            {t('peers.fileAction')}
          </Button>
        )}
        {fetchFile.isError && <p className="text-xs text-destructive">{fetchFile.error.message}</p>}
        {remove.isError && <p className="text-xs text-destructive">{remove.error.message}</p>}
      </div>
    </Card>
  )
}

const AddPeer = ({ onFile }: { onFile: (file: PeerFile) => void }) => {
  const t = useT()
  const add = peerAddMutation.useMutation()
  const [name, setName] = useState('')
  const [tunnelOnly, setTunnelOnly] = useState(false)
  const wrong = name !== '' && !PEER_NAME.test(name)
  const submit = async () => {
    const { file } = await add.mutateAsync({ name, tunnel_only: tunnelOnly })
    setName('')
    setTunnelOnly(false)
    onFile(file)
    await peersQuery.refetchQuery()
  }
  return (
    <div className="space-y-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Input
          value={name}
          placeholder={EXAMPLE_PEER}
          maxLength={32}
          className="w-48 font-mono"
          aria-label={t('peers.add.name')}
          onChange={(event) => setName(event.target.value.trim().toLowerCase())}
        />
        <Button disabled={!name || wrong} loading={add.isPending} onClick={() => void submit()}>
          {t('peers.add.submit')}
        </Button>
      </div>
      {wrong && <p className="text-xs text-destructive">{t('peers.add.nameProblem')}</p>}
      <label className="flex items-center gap-2">
        <XSwitch checked={tunnelOnly} onCheckedChange={setTunnelOnly} />
        <span>{t('peers.add.tunnelOnly')}</span>
      </label>
      {add.isError && <p className="text-xs text-destructive">{add.error.message}</p>}
    </div>
  )
}

export const peersPage = generalLayout.lets
  .page('/peers')
  .search(z.object({ peer: z.string().optional() }))
  .use(redirectUnauthorizedPlugin)
  .page(({ search, setSearch }) => {
    const t = useT()
    useHead({ title: t('nav.peers') })
    const listed = peersQuery.useQuery().data
    const peers = listed?.peers ?? []
    const totals = peerTrafficQuery.useQuery().data?.totals ?? []
    const [file, setFile] = useState<PeerFile | null>(null)
    const picked = pickPeer(
      peers.map((peer) => peer.name),
      search.peer,
    )
    const pick = (key: string) => setSearch({ peer: key })
    const shown = peers.find((peer) => peer.name === picked)
    const detail = (
      <div className="flex min-w-0 flex-col gap-6">
        {shown ? (
          <PeerDetail
            peer={shown}
            checkedAt={listed?.checkedAt ?? 0}
            total={totals.find((item) => item.public_key === shown.public_key)}
            file={file}
            onFile={setFile}
            // the file of a removed peer no longer works: it leaves the screen with the peer
            onRemoved={() => setFile(null)}
          />
        ) : (
          <Card compact h2={t('peers.add.title')} size="sm">
            <div className="space-y-3 text-sm">
              <p className="text-muted-foreground">{t('peers.add.description')}</p>
              {/* a new peer opens at once, with its file shown: it is needed right away */}
              <AddPeer
                onFile={(added) => {
                  setFile(added)
                  pick(added.name)
                }}
              />
            </div>
          </Card>
        )}
        <LogsCard scope="peers" />
      </div>
    )
    return (
      <Sections gap="lg">
        <PageTitle title={t('peers.title')} description={t('peers.description')} />
        <ListDetail
          label={t('peers.title')}
          items={peers.map((peer) => {
            const state = peerLinkState(peer, listed?.checkedAt ?? 0)
            return {
              key: peer.name,
              title: peer.name,
              aside: <Badge variant={STATE_BADGES[state]}>{t(STATE_KEYS[state])}</Badge>,
            }
          })}
          picked={picked}
          onPick={pick}
          add={{ key: ADD_PEER, label: t('peers.add.title') }}
          detail={detail}
        />
      </Sections>
    )
  })
