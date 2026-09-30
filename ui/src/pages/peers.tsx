import { useHead } from '@unhead/react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Section, Sections } from '@/components/ui/section'
import { XSwitch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { qrImageSource } from '@/features/access/shared'
import { humanBytes } from '@/features/node/shared'
import {
  peerAddMutation,
  peerFileMutation,
  peerRemoveMutation,
  peerTrafficQuery,
  peersQuery,
} from '@/features/peers/api'
import {
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

const PeerRow = ({
  peer,
  checkedAt,
  total,
  onFile,
  onRemoved,
}: {
  peer: Peer
  checkedAt: number
  total: PeerTraffic | undefined
  onFile: (file: PeerFile) => void
  onRemoved: (name: string) => void
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
    onRemoved(peer.name)
    await peersQuery.refetchQuery()
  }
  return (
    <TableRow>
      <TableCell>
        <p className="font-mono text-sm">{peer.name}</p>
        {peer.tunnel_only && <p className="text-xs text-muted-foreground">{t('peers.tunnelOnly')}</p>}
      </TableCell>
      <TableCell className="font-mono text-xs">{peer.address}</TableCell>
      <TableCell>
        <Badge variant={STATE_BADGES[state]}>{t(STATE_KEYS[state])}</Badge>
        {peer.latest_handshake ? (
          <p className="mt-1 text-xs text-muted-foreground">
            {formatDate(new Date(peer.latest_handshake * MS_PER_SECOND), 'date-time', language)}
          </p>
        ) : null}
      </TableCell>
      <TableCell className="text-xs whitespace-nowrap">
        {total
          ? t('peers.traffic', { rx: humanBytes(total.rx_bytes), tx: humanBytes(total.tx_bytes) })
          : t('common.none')}
      </TableCell>
      <TableCell className="whitespace-nowrap">
        <Button variant="ghost" size="sm" loading={fetchFile.isPending} onClick={() => void showFile()}>
          {t('peers.fileAction')}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          loading={remove.isPending}
          confirm={t('peers.confirmRemove', { name: peer.name })}
          onClick={() => void drop()}
        >
          {t('common.remove')}
        </Button>
        {fetchFile.isError && <p className="mt-1 text-xs text-destructive">{fetchFile.error.message}</p>}
        {remove.isError && <p className="mt-1 text-xs text-destructive">{remove.error.message}</p>}
      </TableCell>
    </TableRow>
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
  .use(redirectUnauthorizedPlugin)
  .page(() => {
    const t = useT()
    useHead({ title: t('nav.peers') })
    const listed = peersQuery.useQuery().data
    const peers = listed?.peers ?? []
    const totals = peerTrafficQuery.useQuery().data?.totals ?? []
    const [file, setFile] = useState<PeerFile | null>(null)
    const totalOf = (peer: Peer) => totals.find((item) => item.public_key === peer.public_key)

    return (
      <Sections gap="lg">
        <Section h1={t('peers.title')} description={t('peers.description')}>
          {file && <FileCard file={file} onClose={() => setFile(null)} />}
          {peers.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t('peers.empty')}</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('peers.column.name')}</TableHead>
                  <TableHead>{t('peers.column.address')}</TableHead>
                  <TableHead>{t('peers.column.state')}</TableHead>
                  <TableHead>{t('peers.column.traffic', { days: TRAFFIC_DAYS })}</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {peers.map((peer) => (
                  <PeerRow
                    key={peer.name}
                    peer={peer}
                    checkedAt={listed?.checkedAt ?? 0}
                    total={totalOf(peer)}
                    onFile={setFile}
                    // the file of a removed peer no longer works: it leaves the screen with the peer
                    onRemoved={(name) => setFile((shown) => (shown?.name === name ? null : shown))}
                  />
                ))}
              </TableBody>
            </Table>
          )}
        </Section>
        <Section h2={t('peers.add.title')} size="lg" description={t('peers.add.description')}>
          <AddPeer onFile={setFile} />
        </Section>
      </Sections>
    )
  })
