import { useHead } from '@unhead/react'
import { ListDetail } from '@/components/blocks/list-detail'
import { PageTitle } from '@/components/blocks/page-title'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { FilePicker } from '@/components/ui/file-picker'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Sections } from '@/components/ui/section'
import { Textarea } from '@/components/ui/textarea'
import {
  torBridgesMutation,
  torExitMutation,
  torExitQuery,
  xrayExitMutation,
  xrayExitQuery,
  wgExitAddMutation,
  wgExitRemoveMutation,
  wgExitsQuery,
} from '@/features/uplinks/api'
import {
  ADD_EXIT,
  bridgeLinesProblem,
  bridgeLines,
  exitEntries,
  exitKey,
  pickExit,
  MAX_WG_FILE_BYTES,
  missingWgParts,
  PROTON_ACCOUNT_URL,
  PROTON_GUIDE_URL,
  suggestExitName,
  WG_EXIT_NAME,
  MAX_TOR_BRIDGES,
  TOR_KEY,
  MAX_XRAY_LINK_BYTES,
  XRAY_KEY,
  xrayLinkProblem,
  type TorExit,
  type XrayExit,
  type WgExit,
} from '@/features/uplinks/shared'
import { ApplyLine } from '@/features/uplinks/apply-line'
import { LogsCard } from '@/features/logs/card'
import { generalLayout } from '@/layouts/general'
import { redirectUnauthorizedPlugin } from '@/modules/auth/plugins'
import { useT } from '@/modules/i18n/use-t'
import { useState } from 'react'
import { z } from 'zod'

/** The removal of a WireGuard exit and what is known of it: its key and whether its file is on the box */
const WgDetail = ({ exit }: { exit: WgExit }) => {
  const remove = wgExitRemoveMutation.useMutation()
  const t = useT()
  const drop = async () => {
    await remove.mutateAsync({ name: exit.name })
    await wgExitsQuery.refetchQuery()
  }
  return (
    <Card
      compact
      h2={exitKey(exit.name)}
      size="sm"
      action={
        <Button
          variant="outline-secondary"
          size="sm"
          loading={remove.isPending}
          confirm={t('uplinks.confirmRemove', { name: exit.name })}
          onClick={() => void drop()}
        >
          {t('common.remove')}
        </Button>
      }
    >
      <div className="space-y-3 text-sm">
        <p className="text-muted-foreground">{t('uplinks.description')}</p>
        <Badge variant={exit.has_file ? 'success' : 'destructive'}>
          {exit.has_file ? t('uplinks.file.present') : t('uplinks.file.missing')}
        </Badge>
        <p className="text-muted-foreground">{t('uplinks.use')}</p>
        {remove.isError && <p className="text-destructive">{remove.error.message}</p>}
      </div>
    </Card>
  )
}

const TorDetail = ({ tor }: { tor: TorExit }) => {
  const toggle = torExitMutation.useMutation()
  const t = useT()
  const flip = async () => {
    await toggle.mutateAsync({ enabled: !tor.enabled })
    await torExitQuery.refetchQuery()
  }
  return (
    <Card
      compact
      h2={t('uplinks.tor.title')}
      size="sm"
      action={
        <Button
          variant={tor.enabled ? 'outline-secondary' : 'default'}
          size="sm"
          loading={toggle.isPending}
          confirm={tor.enabled ? t('uplinks.tor.confirmOff') : undefined}
          onClick={() => void flip()}
        >
          {tor.enabled ? t('uplinks.tor.disable') : t('uplinks.tor.enable')}
        </Button>
      }
    >
      <div className="space-y-3 text-sm">
        <p className="text-muted-foreground">{t('uplinks.tor.description')}</p>
        {toggle.isError && <p className="text-destructive">{toggle.error.message}</p>}
        <ApplyLine apply={tor.apply} />
        <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
          <li>{t('uplinks.tor.limits.tcp')}</li>
          <li>{t('uplinks.tor.limits.speed')}</li>
          <li>{t('uplinks.tor.limits.start')}</li>
        </ul>
        <p className="text-muted-foreground">{t('uplinks.tor.use')}</p>
        <TorBridges tor={tor} />
      </div>
    </Card>
  )
}

/** The bridges of the exit through Tor: the built-in ones or the owner's own, replaced and given back here */
const TorBridges = ({ tor }: { tor: TorExit }) => {
  const save = torBridgesMutation.useMutation()
  const t = useT()
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState('')
  const problem = text ? bridgeLinesProblem(text) : null
  const apply = async (bridges: string[] | null) => {
    await save.mutateAsync({ bridges })
    await torExitQuery.refetchQuery()
    setEditing(false)
    setText('')
  }
  return (
    <div className="space-y-2">
      <p className="font-mono text-xs text-muted-foreground">
        {t(tor.custom ? 'uplinks.tor.bridges.own' : 'uplinks.tor.bridges.builtIn', {
          bridges: tor.bridges.join(', '),
        })}
      </p>
      {editing ? (
        <div className="space-y-2">
          <label className="block space-y-1">
            <span className="block">{t('uplinks.tor.bridges.paste')}</span>
            <Textarea
              value={text}
              rows={5}
              autoComplete="off"
              spellCheck={false}
              className="font-mono text-xs"
              onChange={(event) => setText(event.target.value)}
            />
            <span className="block text-xs text-muted-foreground">{t('uplinks.tor.bridges.hint')}</span>
          </label>
          {problem && (
            <p className="text-destructive">
              {'line' in problem
                ? t(`uplinks.tor.bridges.problem.${problem.kind}`, { line: problem.line })
                : t(`uplinks.tor.bridges.problem.${problem.kind}`, { max: MAX_TOR_BRIDGES })}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              disabled={problem !== null || !text}
              loading={save.isPending}
              onClick={() => void apply(bridgeLines(text))}
            >
              {t('uplinks.tor.bridges.save')}
            </Button>
            <Button size="sm" variant="outline-secondary" onClick={() => setEditing(false)}>
              {t('uplinks.tor.bridges.cancel')}
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline-secondary" onClick={() => setEditing(true)}>
            {t('uplinks.tor.bridges.replace')}
          </Button>
          {tor.custom && (
            <Button
              size="sm"
              variant="outline-secondary"
              loading={save.isPending}
              confirm={t('uplinks.tor.bridges.confirmReset')}
              onClick={() => void apply(null)}
            >
              {t('uplinks.tor.bridges.reset')}
            </Button>
          )}
        </div>
      )}
      {save.isSuccess && !editing && (
        <p className="text-muted-foreground">
          {t(tor.enabled ? 'uplinks.tor.bridges.savedOn' : 'uplinks.tor.bridges.savedOff')}
        </p>
      )}
      {save.isError && <p className="text-destructive">{save.error.message}</p>}
    </div>
  )
}

const XrayDetail = ({ xray }: { xray: XrayExit }) => {
  const save = xrayExitMutation.useMutation()
  const [link, setLink] = useState('')
  const t = useT()
  const problem = link ? xrayLinkProblem(link) : null
  const apply = async (enabled: boolean, withLink: boolean) => {
    await save.mutateAsync({ enabled, link: withLink ? link.trim() : null })
    await xrayExitQuery.refetchQuery()
    if (withLink) {
      setLink('')
    }
  }
  return (
    <Card
      compact
      h2={t('uplinks.xray.title')}
      size="sm"
      action={
        <Button
          variant={xray.enabled ? 'outline-secondary' : 'default'}
          size="sm"
          disabled={!xray.linked && !xray.enabled}
          loading={save.isPending}
          confirm={xray.enabled ? t('uplinks.xray.confirmOff') : undefined}
          onClick={() => void apply(!xray.enabled, false)}
        >
          {xray.enabled ? t('uplinks.xray.disable') : t('uplinks.xray.enable')}
        </Button>
      }
    >
      <div className="space-y-3 text-sm">
        <p className="text-muted-foreground">{t('uplinks.xray.description')}</p>
        {xray.linked && !xray.problem && (
          <p>
            {t('uplinks.xray.server', { endpoint: xray.endpoint, transport: xray.transport })}
            {xray.remark && ` — ${xray.remark}`}
          </p>
        )}
        {xray.problem && <p className="text-destructive">{xray.problem}</p>}
        {!xray.linked && <p className="text-muted-foreground">{t('uplinks.xray.noLink')}</p>}
        <label className="block space-y-1">
          <span className="block">{t('uplinks.xray.link')}</span>
          <div className="flex flex-wrap gap-2">
            <Input
              value={link}
              maxLength={MAX_XRAY_LINK_BYTES}
              autoComplete="off"
              spellCheck={false}
              className="min-w-0 flex-1"
              onChange={(event) => setLink(event.target.value)}
            />
            <Button
              size="sm"
              disabled={problem !== null || !link}
              loading={save.isPending}
              onClick={() => void apply(xray.enabled, true)}
            >
              {t('uplinks.xray.save')}
            </Button>
          </div>
          <span className="block text-xs text-muted-foreground">{t('uplinks.xray.linkHint')}</span>
        </label>
        {problem && <p className="text-destructive">{t(`uplinks.xray.problem.${problem}`)}</p>}
        {save.isSuccess && save.variables.link !== null && (
          <p className="text-muted-foreground">{t('uplinks.xray.saved')}</p>
        )}
        {save.isError && <p className="text-destructive">{save.error.message}</p>}
        <ApplyLine apply={xray.apply} />
        <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
          <li>{t('uplinks.xray.limits.tcp')}</li>
          <li>{t('uplinks.xray.limits.speed')}</li>
          <li>{t('uplinks.xray.limits.down')}</li>
        </ul>
        <p className="text-muted-foreground">{t('uplinks.xray.use')}</p>
      </div>
    </Card>
  )
}

const ProtonGuide = () => {
  const t = useT()
  return (
    <div className="space-y-2 text-sm">
      <p>{t('uplinks.guide.intro')}</p>
      <ol className="list-decimal space-y-1 pl-5">
        <li>{t('uplinks.guide.step1')}</li>
        <li>{t('uplinks.guide.step2')}</li>
        <li>{t('uplinks.guide.step3')}</li>
        <li>{t('uplinks.guide.step4')}</li>
      </ol>
      <div className="flex flex-wrap gap-3">
        <a className="underline" href={PROTON_ACCOUNT_URL} target="_blank" rel="noreferrer">
          {t('uplinks.guide.openProton')}
        </a>
        <a className="underline" href={PROTON_GUIDE_URL} target="_blank" rel="noreferrer">
          {t('uplinks.guide.help')}
        </a>
      </div>
      <p className="text-muted-foreground">{t('uplinks.guide.other')}</p>
    </div>
  )
}

const AddExit = ({ onAdded }: { onAdded: (key: string) => void }) => {
  const add = wgExitAddMutation.useMutation()
  const t = useT()
  const [name, setName] = useState('')
  const [text, setText] = useState('')
  const [tooLarge, setTooLarge] = useState(false)
  const missing = text ? missingWgParts(text) : []

  const chooseFile = async (file: File | null) => {
    if (!file) {
      return
    }
    setTooLarge(file.size > MAX_WG_FILE_BYTES)
    if (file.size > MAX_WG_FILE_BYTES) {
      return
    }
    setText(await file.text())
    setName((current) => current || suggestExitName(file.name))
  }

  const submit = async () => {
    await add.mutateAsync({ name, config: text })
    setText('')
    setName('')
    await wgExitsQuery.refetchQuery()
    onAdded(exitKey(name))
  }

  return (
    <Card compact h2={t('uplinks.add.title')} size="sm">
      <ProtonGuide />
      <div className="mt-4 space-y-3">
        <div className="space-y-1 text-sm">
          <span className="block">{t('uplinks.add.file')}</span>
          <FilePicker
            accept=".conf,text/plain"
            label={t('uplinks.add.file')}
            onPick={(file) => void chooseFile(file)}
          />
        </div>
        {tooLarge && <p className="text-sm text-destructive">{t('uplinks.add.tooLarge')}</p>}
        <label className="block space-y-1 text-sm">
          <span className="block">{t('uplinks.add.paste')}</span>
          <Textarea
            value={text}
            rows={6}
            spellCheck={false}
            className="font-mono text-xs"
            onChange={(event) => setText(event.target.value)}
          />
        </label>
        {missing.length > 0 && (
          <p className="text-sm text-warning">{t('uplinks.add.missing', { parts: missing.join(', ') })}</p>
        )}
        <label className="block space-y-1 text-sm">
          <span className="block">{t('uplinks.add.name')}</span>
          <Input
            value={name}
            maxLength={24}
            className="max-w-xs"
            onChange={(event) => setName(event.target.value.trim().toLowerCase())}
          />
          <span className="block text-xs text-muted-foreground">{t('uplinks.add.nameHint')}</span>
        </label>
        <p className="text-xs text-muted-foreground">{t('uplinks.add.private')}</p>
        <Button
          disabled={!WG_EXIT_NAME.test(name) || !text || missing.length > 0}
          loading={add.isPending}
          onClick={() => void submit()}
        >
          {t('uplinks.add.submit')}
        </Button>
        {add.isError && <p className="text-sm text-destructive">{add.error.message}</p>}
      </div>
    </Card>
  )
}

/** The chosen exit: its card, and the log of its service */
const ExitDetail = ({
  picked,
  tor,
  xray,
  wg,
  onAdded,
}: {
  picked: string
  tor: TorExit | undefined
  xray: XrayExit | undefined
  wg: WgExit[]
  onAdded: (key: string) => void
}) => {
  const exit = wg.find((item) => exitKey(item.name) === picked)
  return (
    <div className="flex min-w-0 flex-col gap-6">
      {picked === ADD_EXIT && <AddExit onAdded={onAdded} />}
      {picked === TOR_KEY && tor && <TorDetail tor={tor} />}
      {picked === XRAY_KEY && xray && <XrayDetail xray={xray} />}
      {exit && <WgDetail exit={exit} />}
      {picked !== ADD_EXIT && <LogsCard scope="uplinks" service={picked} />}
    </div>
  )
}

export const uplinksPage = generalLayout.lets
  .page('/uplinks')
  .use(redirectUnauthorizedPlugin)
  .search(z.object({ exit: z.string().optional() }))
  .page(({ search, setSearch }) => {
    const t = useT()
    useHead({ title: t('nav.uplinks') })
    const data = wgExitsQuery.useQuery().data
    const exits = data?.exits
    const tor = torExitQuery.useQuery().data?.tor ?? undefined
    const xray = xrayExitQuery.useQuery().data?.xray ?? undefined
    const wg = exits?.uplinks ?? []
    const entries = exitEntries(tor, xray, wg)
    const picked = pickExit(entries, search.exit)
    const pick = (key: string) => setSearch({ exit: key })
    const detail = <ExitDetail picked={picked} tor={tor} xray={xray} wg={wg} onAdded={pick} />

    return (
      <Sections gap="lg">
        <PageTitle title={t('uplinks.page.title')} description={t('uplinks.page.description')} />
        {data && !exits && <p className="text-sm text-muted-foreground">{data.reason}</p>}
        {exits && <ApplyLine apply={exits.apply} />}
        <ListDetail
          label={t('uplinks.page.title')}
          items={entries.map((entry) => ({
            key: entry.key,
            title: entry.kind === 'wg' ? entry.key : t(`uplinks.${entry.kind}.title`),
            aside: (
              <Badge variant={entry.on ? 'success' : 'secondary'}>
                {entry.on ? t('uplinks.list.on') : t('uplinks.list.off')}
              </Badge>
            ),
          }))}
          picked={picked}
          onPick={pick}
          add={exits ? { key: ADD_EXIT, label: t('uplinks.list.add') } : undefined}
          detail={detail}
        />
      </Sections>
    )
  })
