import { useHead } from '@unhead/react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Section, Sections } from '@/components/ui/section'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  accessMutation,
  accessQuery,
  ddnsMutation,
  ddnsQuery,
  personAddMutation,
  personLinkMutation,
  personRemoveMutation,
} from '@/features/access/api'
import {
  addressLooksValid,
  ddnsUrlProblem,
  MAX_DDNS_URL_BYTES,
  PERSON_NAME_MAX,
  personNameProblem,
  qrImageSource,
  type AccessLink,
  type AccessPerson,
  type AccessServer,
  type Ddns,
} from '@/features/access/shared'
import { humanBytes } from '@/features/node/shared'
import { ApplyLine } from '@/features/uplinks/apply-line'
import { generalLayout } from '@/layouts/general'
import { redirectUnauthorizedPlugin } from '@/modules/auth/plugins'
import { useLanguage, useT } from '@/modules/i18n/use-t'
import { formatDate } from '@/utils/date'
import { useState } from 'react'

const LinkCard = ({ link, onClose }: { link: AccessLink; onClose: () => void }) => {
  const t = useT()
  const [copied, setCopied] = useState(false)
  // the clipboard exists only on https, and the panel of a box is plain http on the LAN
  const canCopy = typeof window !== 'undefined' && window.isSecureContext
  const copy = async () => {
    await navigator.clipboard.writeText(link.link)
    setCopied(true)
  }
  return (
    <div className="space-y-3 rounded-md border p-4 text-sm">
      <p className="font-semibold">{t('access.link.title', { name: link.name })}</p>
      <img
        src={qrImageSource(link.qr_svg)}
        alt={t('access.link.qrAlt', { name: link.name })}
        className="size-64 max-w-full"
      />
      <Input
        readOnly
        value={link.link}
        spellCheck={false}
        className="font-mono text-xs"
        onFocus={(event) => event.target.select()}
      />
      <div className="flex flex-wrap gap-2">
        {canCopy && (
          <Button size="sm" onClick={() => void copy()}>
            {copied ? t('access.link.copied') : t('access.link.copy')}
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={onClose}>
          {t('access.link.hide')}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">{t('access.link.warning')}</p>
      <p className="text-xs text-muted-foreground">{t('access.link.apps')}</p>
    </div>
  )
}

const ServerCard = ({ server }: { server: AccessServer }) => {
  const save = accessMutation.useMutation()
  const t = useT()
  const [address, setAddress] = useState(server.address)
  const [target, setTarget] = useState(server.target)
  const apply = async (enabled: boolean) => {
    await save.mutateAsync({ enabled, address: address.trim() || null, target: target.trim() || null })
    await accessQuery.refetchQuery()
  }
  const endpoint = `${server.address}:${server.port}`
  return (
    <Section h1={t('access.title')} description={t('access.description')}>
      <div className="space-y-3 text-sm">
        <div className="flex flex-wrap items-center gap-3">
          <Badge variant={server.enabled ? 'success' : 'secondary'}>
            {server.enabled ? t('access.on') : t('access.off')}
          </Badge>
          {server.enabled && <span className="font-mono text-xs text-muted-foreground">{endpoint}</span>}
        </div>
        <label className="block space-y-1">
          <span>{t('access.address')}</span>
          <Input
            value={address}
            maxLength={253}
            className="max-w-md"
            spellCheck={false}
            onChange={(event) => setAddress(event.target.value.trim())}
          />
          <span className="block text-xs text-muted-foreground">{t('access.addressHint')}</span>
        </label>
        <label className="block space-y-1">
          <span>{t('access.target')}</span>
          <Input
            value={target}
            maxLength={253}
            className="max-w-md"
            spellCheck={false}
            onChange={(event) => setTarget(event.target.value.trim())}
          />
          <span className="block text-xs text-muted-foreground">{t('access.targetHint')}</span>
        </label>
        <div className="flex flex-wrap gap-2">
          <Button disabled={!addressLooksValid(address)} loading={save.isPending} onClick={() => void apply(true)}>
            {server.enabled ? t('access.save') : t('access.enable')}
          </Button>
          {server.enabled && (
            <Button
              variant="ghost"
              loading={save.isPending}
              confirm={t('access.confirmOff')}
              onClick={() => void apply(false)}
            >
              {t('access.disable')}
            </Button>
          )}
        </div>
        {save.isError && <p className="text-destructive">{save.error.message}</p>}
        <ApplyLine apply={server.apply} />
        {server.enabled && <p className="text-muted-foreground">{t('access.forward', { port: server.port })}</p>}
        <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
          <li>{t('access.limits.home')}</li>
          <li>{t('access.limits.lan')}</li>
          <li>{t('access.limits.strangers')}</li>
        </ul>
      </div>
    </Section>
  )
}

const PersonRow = ({ person, onShow }: { person: AccessPerson; onShow: (link: AccessLink) => void }) => {
  const t = useT()
  const language = useLanguage()
  const reveal = personLinkMutation.useMutation()
  const remove = personRemoveMutation.useMutation()
  const show = async () => {
    onShow((await reveal.mutateAsync({ name: person.name })).link)
  }
  const drop = async () => {
    await remove.mutateAsync({ name: person.name })
    await accessQuery.refetchQuery()
  }
  return (
    <TableRow>
      <TableCell>{person.name}</TableCell>
      <TableCell>{formatDate(new Date(person.created), 'date', language)}</TableCell>
      <TableCell>
        {t('access.people.traffic', { down: humanBytes(person.tx_bytes), up: humanBytes(person.rx_bytes) })}
      </TableCell>
      <TableCell>
        <div className="flex flex-wrap gap-2">
          <Button variant="ghost" size="sm" loading={reveal.isPending} onClick={() => void show()}>
            {t('access.people.showLink')}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            loading={remove.isPending}
            confirm={t('access.people.confirmRemove', { name: person.name })}
            onClick={() => void drop()}
          >
            {t('common.remove')}
          </Button>
        </div>
        {(reveal.isError || remove.isError) && (
          <p className="mt-1 text-xs text-destructive">{(reveal.error ?? remove.error)?.message}</p>
        )}
      </TableCell>
    </TableRow>
  )
}

const PeopleCard = ({ server }: { server: AccessServer }) => {
  const add = personAddMutation.useMutation()
  const t = useT()
  const [name, setName] = useState('')
  const [shown, setShown] = useState<AccessLink | null>(null)
  const problem = name ? personNameProblem(name) : null
  const submit = async () => {
    const answer = await add.mutateAsync({ name })
    setShown(answer.link)
    setName('')
    await accessQuery.refetchQuery()
  }
  return (
    <Section h2={t('access.people.title')} description={t('access.people.description')}>
      <div className="space-y-3 text-sm">
        {server.people.length === 0 ? (
          <p className="text-muted-foreground">{t('access.people.empty')}</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('access.people.column.name')}</TableHead>
                <TableHead>{t('access.people.column.since')}</TableHead>
                <TableHead>{t('access.people.column.traffic')}</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {server.people.map((person) => (
                <PersonRow key={person.name} person={person} onShow={setShown} />
              ))}
            </TableBody>
          </Table>
        )}
        {shown && <LinkCard link={shown} onClose={() => setShown(null)} />}
        <label className="block space-y-1">
          <span>{t('access.people.name')}</span>
          <Input
            value={name}
            maxLength={PERSON_NAME_MAX}
            className="max-w-xs"
            onChange={(event) => setName(event.target.value.trim().toLowerCase())}
          />
          <span className="block text-xs text-muted-foreground">{t('access.people.nameHint')}</span>
        </label>
        <Button
          disabled={!server.enabled || !name || problem !== null}
          loading={add.isPending}
          onClick={() => void submit()}
        >
          {t('access.people.add')}
        </Button>
        {!server.enabled && <p className="text-muted-foreground">{t('access.people.offFirst')}</p>}
        {problem && <p className="text-destructive">{t(`access.people.problem.${problem}`)}</p>}
        {add.isError && <p className="text-destructive">{add.error.message}</p>}
      </div>
    </Section>
  )
}

const DdnsCard = ({ ddns }: { ddns: Ddns }) => {
  const save = ddnsMutation.useMutation()
  const t = useT()
  const language = useLanguage()
  const [url, setUrl] = useState('')
  const problem = url ? ddnsUrlProblem(url) : null
  const apply = async (enabled: boolean, withUrl: boolean) => {
    await save.mutateAsync({ enabled, url: withUrl ? url.trim() : null })
    if (withUrl) {
      setUrl('')
    }
    await ddnsQuery.refetchQuery()
  }
  const lastTime = ddns.last_at === null ? null : formatDate(new Date(ddns.last_at * 1000), 'date-time-nice', language)
  return (
    <Section h2={t('access.ddns.title')} description={t('access.ddns.description')}>
      <div className="space-y-3 text-sm">
        <div className="flex flex-wrap items-center gap-3">
          <Badge variant={ddns.enabled ? 'success' : 'secondary'}>
            {ddns.enabled ? t('access.ddns.on') : t('access.ddns.off')}
          </Badge>
          {ddns.host && <span className="font-mono text-xs text-muted-foreground">{ddns.host}</span>}
        </div>
        {ddns.public_ip && (
          <p className="text-muted-foreground">
            {t('access.ddns.addresses', { public: ddns.public_ip, told: ddns.told_ip ?? t('common.none') })}
          </p>
        )}
        {lastTime && (
          <p className={ddns.last_ok ? 'text-muted-foreground' : 'text-destructive'}>
            {ddns.last_ok
              ? t('access.ddns.lastOk', { time: lastTime, message: ddns.message })
              : t('access.ddns.lastFailed', { time: lastTime, message: ddns.message })}
          </p>
        )}
        {ddns.address_error && (
          <p className="text-warning">{t('access.ddns.addressFailed', { message: ddns.address_error })}</p>
        )}
        <label className="block space-y-1">
          <span>{t('access.ddns.url')}</span>
          <Input
            type="password"
            value={url}
            maxLength={MAX_DDNS_URL_BYTES}
            autoComplete="off"
            spellCheck={false}
            onChange={(event) => setUrl(event.target.value)}
          />
          <span className="block text-xs text-muted-foreground">{t('access.ddns.urlHint')}</span>
        </label>
        <div className="flex flex-wrap gap-2">
          <Button disabled={!url || problem !== null} loading={save.isPending} onClick={() => void apply(true, true)}>
            {t('access.ddns.save')}
          </Button>
          {ddns.enabled && (
            <Button variant="ghost" loading={save.isPending} onClick={() => void apply(false, false)}>
              {t('access.ddns.disable')}
            </Button>
          )}
          {!ddns.enabled && ddns.url_set && (
            <Button variant="ghost" loading={save.isPending} onClick={() => void apply(true, false)}>
              {t('access.ddns.enable')}
            </Button>
          )}
        </div>
        {problem && <p className="text-destructive">{t(`access.ddns.problem.${problem}`)}</p>}
        {save.isError && <p className="text-destructive">{save.error.message}</p>}
        <ApplyLine apply={ddns.apply} />
        <p className="text-muted-foreground">{t('access.ddns.services')}</p>
      </div>
    </Section>
  )
}

export const accessPage = generalLayout.lets
  .page('/access')
  .use(redirectUnauthorizedPlugin)
  .page(() => {
    const t = useT()
    useHead({ title: t('nav.access') })
    const data = accessQuery.useQuery().data
    const server = data?.server
    const ddns = ddnsQuery.useQuery().data?.ddns

    return (
      <Sections gap="lg">
        {data && !server && (
          <Section h1={t('access.title')}>
            <p className="text-sm text-muted-foreground">{data.reason}</p>
          </Section>
        )}
        {server && <ServerCard server={server} />}
        {server && <PeopleCard server={server} />}
        {ddns && <DdnsCard ddns={ddns} />}
      </Sections>
    )
  })
