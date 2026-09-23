import { useHead } from '@unhead/react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Section, Sections } from '@/components/ui/section'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
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
  exitKey,
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
import { generalLayout } from '@/layouts/general'
import { redirectUnauthorizedPlugin } from '@/modules/auth/plugins'
import { useT } from '@/modules/i18n/use-t'
import { useState, type ChangeEvent } from 'react'

const ExitRow = ({ exit }: { exit: WgExit }) => {
  const remove = wgExitRemoveMutation.useMutation()
  const t = useT()
  const drop = async () => {
    await remove.mutateAsync({ name: exit.name })
    await wgExitsQuery.refetchQuery()
  }
  return (
    <TableRow>
      <TableCell>
        <div>{exit.name}</div>
        <div className="font-mono text-xs text-muted-foreground">{exitKey(exit.name)}</div>
      </TableCell>
      <TableCell>
        <Badge variant={exit.has_file ? 'success' : 'destructive'}>
          {exit.has_file ? t('uplinks.file.present') : t('uplinks.file.missing')}
        </Badge>
      </TableCell>
      <TableCell>
        <Button
          variant="ghost"
          size="sm"
          loading={remove.isPending}
          confirm={t('uplinks.confirmRemove', { name: exit.name })}
          onClick={() => void drop()}
        >
          {t('common.remove')}
        </Button>
        {remove.isError && <p className="mt-1 text-xs text-destructive">{remove.error.message}</p>}
      </TableCell>
    </TableRow>
  )
}

const TorCard = ({ tor }: { tor: TorExit }) => {
  const toggle = torExitMutation.useMutation()
  const t = useT()
  const flip = async () => {
    await toggle.mutateAsync({ enabled: !tor.enabled })
    await torExitQuery.refetchQuery()
  }
  return (
    <Section h2={t('uplinks.tor.title')} description={t('uplinks.tor.description')}>
      <div className="space-y-3 text-sm">
        <div className="flex flex-wrap items-center gap-3">
          <Badge variant={tor.enabled ? 'success' : 'secondary'}>
            {tor.enabled ? t('uplinks.tor.on') : t('uplinks.tor.off')}
          </Badge>
          <span className="font-mono text-xs text-muted-foreground">{TOR_KEY}</span>
          <Button
            variant={tor.enabled ? 'ghost' : 'default'}
            size="sm"
            loading={toggle.isPending}
            confirm={tor.enabled ? t('uplinks.tor.confirmOff') : undefined}
            onClick={() => void flip()}
          >
            {tor.enabled ? t('uplinks.tor.disable') : t('uplinks.tor.enable')}
          </Button>
        </div>
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
    </Section>
  )
}

const XrayCard = ({ xray }: { xray: XrayExit }) => {
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
    <Section h2={t('uplinks.xray.title')} description={t('uplinks.xray.description')}>
      <div className="space-y-3 text-sm">
        <div className="flex flex-wrap items-center gap-3">
          <Badge variant={xray.enabled ? 'success' : 'secondary'}>
            {xray.enabled ? t('uplinks.xray.on') : t('uplinks.xray.off')}
          </Badge>
          <span className="font-mono text-xs text-muted-foreground">{XRAY_KEY}</span>
          <Button
            variant={xray.enabled ? 'ghost' : 'default'}
            size="sm"
            disabled={!xray.linked && !xray.enabled}
            loading={save.isPending}
            confirm={xray.enabled ? t('uplinks.xray.confirmOff') : undefined}
            onClick={() => void apply(!xray.enabled, false)}
          >
            {xray.enabled ? t('uplinks.xray.disable') : t('uplinks.xray.enable')}
          </Button>
        </div>
        {xray.linked && !xray.problem && (
          <p className="text-muted-foreground">
            {t('uplinks.xray.server', { endpoint: xray.endpoint, transport: xray.transport })}
            {xray.remark && ` — ${xray.remark}`}
          </p>
        )}
        {xray.problem && <p className="text-destructive">{xray.problem}</p>}
        {!xray.linked && <p className="text-muted-foreground">{t('uplinks.xray.noLink')}</p>}
        <label className="block space-y-1">
          <span>{t('uplinks.xray.link')}</span>
          <Input
            value={link}
            maxLength={MAX_XRAY_LINK_BYTES}
            autoComplete="off"
            spellCheck={false}
            onChange={(event) => setLink(event.target.value)}
          />
          <span className="block text-xs text-muted-foreground">{t('uplinks.xray.linkHint')}</span>
        </label>
        <Button
          size="sm"
          disabled={problem !== null || !link}
          loading={save.isPending}
          onClick={() => void apply(xray.enabled, true)}
        >
          {t('uplinks.xray.save')}
        </Button>
        {problem && <p className="text-sm text-destructive">{t(`uplinks.xray.problem.${problem}`)}</p>}
        {save.isError && <p className="text-destructive">{save.error.message}</p>}
        <ApplyLine apply={xray.apply} />
        <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
          <li>{t('uplinks.xray.limits.tcp')}</li>
          <li>{t('uplinks.xray.limits.speed')}</li>
          <li>{t('uplinks.xray.limits.down')}</li>
        </ul>
        <p className="text-muted-foreground">{t('uplinks.xray.use')}</p>
      </div>
    </Section>
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

const AddExit = () => {
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
  }

  return (
    <Section h2={t('uplinks.add.title')}>
      <ProtonGuide />
      <div className="mt-4 space-y-3">
        <label className="block space-y-1 text-sm">
          <span>{t('uplinks.add.file')}</span>
          <Input type="file" accept=".conf,text/plain" onChange={(event) => void chooseFile(event)} />
        </label>
        {tooLarge && <p className="text-sm text-destructive">{t('uplinks.add.tooLarge')}</p>}
        <label className="block space-y-1 text-sm">
          <span>{t('uplinks.add.paste')}</span>
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
          <span>{t('uplinks.add.name')}</span>
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
    </Section>
  )
}

export const uplinksPage = generalLayout.lets
  .page('/uplinks')
  .use(redirectUnauthorizedPlugin)
  .page(() => {
    const t = useT()
    useHead({ title: t('nav.uplinks') })
    const data = wgExitsQuery.useQuery().data
    const exits = data?.exits
    const tor = torExitQuery.useQuery().data?.tor
    const xray = xrayExitQuery.useQuery().data?.xray

    return (
      <Sections gap="lg">
        {tor && <TorCard tor={tor} />}
        {xray && <XrayCard xray={xray} />}
        <Section h1={t('uplinks.title')} description={t('uplinks.description')}>
          {data && !exits && <p className="text-sm text-muted-foreground">{data.reason}</p>}
          {exits && (
            <div className="space-y-3">
              <ApplyLine apply={exits.apply} />
              {exits.uplinks.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t('uplinks.empty')}</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t('uplinks.column.name')}</TableHead>
                      <TableHead>{t('uplinks.column.file')}</TableHead>
                      <TableHead />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {exits.uplinks.map((exit) => (
                      <ExitRow key={exit.name} exit={exit} />
                    ))}
                  </TableBody>
                </Table>
              )}
              <p className="text-sm text-muted-foreground">{t('uplinks.use')}</p>
            </div>
          )}
        </Section>
        {exits && <AddExit />}
      </Sections>
    )
  })
