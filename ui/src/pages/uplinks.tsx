import { useHead } from '@unhead/react'
import { useBreakpoint } from '@/components/hooks/use-breakpoint'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Section, Sections } from '@/components/ui/section'
import { Textarea } from '@/components/ui/textarea'
import {
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
  exitEntries,
  exitKey,
  pickExit,
  type ExitEntry,
  MAX_WG_FILE_BYTES,
  missingWgParts,
  PROTON_ACCOUNT_URL,
  PROTON_GUIDE_URL,
  suggestExitName,
  WG_EXIT_NAME,
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
import { cn } from '@/utils'
import { PlusIcon } from 'lucide-react'
import { useState, type ChangeEvent } from 'react'
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
        <p className="font-mono text-xs text-muted-foreground">
          {t('uplinks.tor.bridges', { bridges: tor.bridges.join(', ') })}
        </p>
      </div>
    </Card>
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

  const chooseFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
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
        <label className="block space-y-1 text-sm">
          <span className="block">{t('uplinks.add.file')}</span>
          <Input type="file" accept=".conf,text/plain" onChange={(event) => void chooseFile(event)} />
        </label>
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

const ExitListItem = ({
  entry,
  current,
  onPick,
}: {
  entry: ExitEntry
  current: boolean
  onPick: (key: string) => void
}) => {
  const t = useT()
  const title = entry.kind === 'wg' ? entry.key : t(`uplinks.${entry.kind}.title`)
  return (
    <button
      type="button"
      data-exit={entry.key}
      aria-current={current || undefined}
      className={cn(
        'flex w-full items-center justify-between gap-3 rounded-lg border border-border px-4 py-3 text-left transition-colors hover:bg-muted',
        current && 'border-primary bg-muted',
      )}
      onClick={() => onPick(entry.key)}
    >
      <span className="min-w-0 font-accent text-sm font-semibold">{title}</span>
      <Badge variant={entry.on ? 'success' : 'secondary'}>{entry.on ? t('uplinks.list.on') : t('uplinks.list.off')}</Badge>
    </button>
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
    const phone = useBreakpoint('max-lg')
    const wg = exits?.uplinks ?? []
    const entries = exitEntries(tor, xray, wg)
    const picked = pickExit(entries, search.exit)
    const pick = (key: string) => setSearch({ exit: key })
    const detail = <ExitDetail picked={picked} tor={tor} xray={xray} wg={wg} onAdded={pick} />

    return (
      <Sections gap="lg">
        <Section h1={t('uplinks.page.title')} description={t('uplinks.page.description')} descriptionClassName="max-w-none text-xl text-pretty max-md:text-lg max-sm:text-base" />
        {data && !exits && <p className="text-sm text-muted-foreground">{data.reason}</p>}
        {exits && <ApplyLine apply={exits.apply} />}
        <div className="grid items-start gap-6 lg:grid-cols-3">
          {/* on a phone the chosen exit opens under its own line, not in a second column */}
          <nav aria-label={t('uplinks.page.title')} className="flex min-w-0 flex-col gap-2">
            {entries.map((entry) => (
              <div key={entry.key} className="flex flex-col gap-4">
                <ExitListItem entry={entry} current={entry.key === picked} onPick={pick} />
                {phone && entry.key === picked && detail}
              </div>
            ))}
            {exits && (
              <div className="flex flex-col gap-4">
                <Button
                  variant={picked === ADD_EXIT ? 'default' : 'outline-secondary'}
                  icon={PlusIcon}
                  onClick={() => pick(ADD_EXIT)}
                >
                  {t('uplinks.list.add')}
                </Button>
                {phone && picked === ADD_EXIT && detail}
              </div>
            )}
          </nav>
          {!phone && <div className="min-w-0 lg:col-span-2">{detail}</div>}
        </div>
      </Sections>
    )
  })
