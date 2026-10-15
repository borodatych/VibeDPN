import { Button } from '@/components/ui/button'
import { FilePicker } from '@/components/ui/file-picker'
import { Input } from '@/components/ui/input'
import { XSwitch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  bytesToBase64,
  MAGNET_EXAMPLE,
  magnetProblem,
  subdirProblem,
  SUBDIR_MAX,
  torrentFileProblem,
} from '@/features/torrents/shared'
import { useT } from '@/modules/i18n/use-t'
import { useState } from 'react'

const SOURCES = ['magnet', 'file'] as const
type Source = (typeof SOURCES)[number]

/** What the form sends to core: exactly one of `magnet` and `torrent` is set. */
export type AddPayload = { magnet: string | null; torrent: string | null; subdir: string | null; paused: boolean }

/**
 * The form of a new torrent: a magnet link or a `.torrent` file, a folder inside the downloads, and whether to start
 *
 * @tags torrents
 */
export const AddForm = ({
  pending,
  error,
  onSubmit,
}: {
  pending: boolean
  error: string | null
  onSubmit: (payload: AddPayload) => void
}) => {
  const t = useT()
  const [source, setSource] = useState<Source>('magnet')
  const [magnet, setMagnet] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [subdir, setSubdir] = useState('')
  const [start, setStart] = useState(true)
  const [readError, setReadError] = useState<string | null>(null)

  const magnetIssue = magnet.trim() === '' ? null : magnetProblem(magnet)
  const fileIssue = file ? torrentFileProblem(file) : null
  const subdirIssue = subdirProblem(subdir)
  const ready =
    subdirIssue === null &&
    (source === 'magnet' ? magnet.trim() !== '' && magnetIssue === null : file !== null && fileIssue === null)

  const submit = async () => {
    setReadError(null)
    const common = { subdir: subdir.trim() || null, paused: !start }
    if (source === 'magnet') {
      onSubmit({ ...common, magnet: magnet.trim(), torrent: null })
      return
    }
    if (!file) {
      return
    }
    try {
      onSubmit({ ...common, magnet: null, torrent: bytesToBase64(new Uint8Array(await file.arrayBuffer())) })
    } catch {
      setReadError(t('torrents.add.readFailed'))
    }
  }

  return (
    <div className="space-y-4 text-sm">
      <Tabs value={source} onValueChange={(value) => setSource(SOURCES.find((s) => s === value) ?? 'magnet')}>
        <TabsList>
          <TabsTrigger value="magnet">{t('torrents.add.magnet')}</TabsTrigger>
          <TabsTrigger value="file">{t('torrents.add.file')}</TabsTrigger>
        </TabsList>
        <TabsContent value="magnet" className="space-y-1">
          <Input
            value={magnet}
            spellCheck={false}
            autoComplete="off"
            placeholder={MAGNET_EXAMPLE}
            aria-label={t('torrents.add.magnet')}
            onChange={(event) => setMagnet(event.target.value)}
          />
          {magnetIssue && <p className="text-destructive">{t(`torrents.add.magnetProblem.${magnetIssue}`)}</p>}
        </TabsContent>
        <TabsContent value="file" className="space-y-1">
          <FilePicker accept=".torrent,application/x-bittorrent" label={t('torrents.add.file')} onPick={setFile} />
          {fileIssue && <p className="text-destructive">{t(`torrents.add.fileProblem.${fileIssue}`)}</p>}
        </TabsContent>
      </Tabs>
      <label className="block space-y-1">
        <span className="block">{t('torrents.add.subdir')}</span>
        <Input
          value={subdir}
          maxLength={SUBDIR_MAX}
          spellCheck={false}
          autoComplete="off"
          onChange={(event) => setSubdir(event.target.value)}
        />
        <span className="block text-xs text-muted-foreground">{t('torrents.add.subdirHint')}</span>
        {subdirIssue && <span className="block text-destructive">{t('torrents.add.subdirProblem')}</span>}
      </label>
      <XSwitch label={t('torrents.add.start')} checked={start} onCheckedChange={setStart} />
      {(error ?? readError) && <p className="text-destructive">{error ?? readError}</p>}
      <Button disabled={!ready} loading={pending} onClick={() => void submit()}>
        {t('torrents.add.submit')}
      </Button>
    </div>
  )
}
