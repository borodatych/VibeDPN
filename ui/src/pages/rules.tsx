import { useHead } from '@unhead/react'
import { ListDetail } from '@/components/blocks/list-detail'
import { PageTitle } from '@/components/blocks/page-title'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Sections } from '@/components/ui/section'
import { XSelect } from '@/components/ui/select'
import { XSwitch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  domainListRemoveMutation,
  domainListSetMutation,
  domainListsQuery,
  journalDevicesQuery,
  journalQuery,
  learnedForgetMutation,
  learnedListQuery,
  networkRuleRemoveMutation,
  networkRuleSetMutation,
  networkRulesQuery,
  ruleListQuery,
  ruleRemoveMutation,
  ruleSetMutation,
} from '@/features/rules/api'
import {
  cdnCandidates,
  channelLabel,
  channelText,
  listCopyText,
  networkProblem,
  TELEGRAM_NETWORKS,
  wgExitNames,
  withCdn,
  type DomainListView,
  type DomainRule,
  type JournalEntry,
  type NetworkRuleView,
  pickSection,
  RULE_SECTIONS,
  ruleVias,
  type RuleSection,
  type OptionalExits,
  type RuleVia,
} from '@/features/rules/shared'
import { boxStatusQuery } from '@/features/status/api'
import { generalLayout } from '@/layouts/general'
import { redirectUnauthorizedPlugin } from '@/modules/auth/plugins'
import type { T } from '@/modules/i18n/base'
import { useLanguage, useT } from '@/modules/i18n/use-t'
import { formatDate } from '@/utils/date'
import { useState, type ReactNode } from 'react'
import { z } from 'zod'

const viaOptions = (t: T, exits: OptionalExits) =>
  ruleVias(exits).map((via) => ({ value: via, label: t(`rules.via.${via}`) }))

const exitOptions = (exits: string[]) => exits.map((name) => ({ value: name, label: name }))

/** The exits of the box that may be off, for the channel choice of rules, lists and networks */
const useOptionalExits = (): OptionalExits => {
  const uplinks = boxStatusQuery.useQuery().data?.status.uplinks ?? []
  const on = (name: string) => uplinks.some((uplink) => uplink.name === name && uplink.enabled)
  return { wg: wgExitNames(uplinks), tor: on('tor'), xray: on('xray') }
}

const SHOWN_QUERIES = 100

// Sample values for the empty inputs: data in the form the field takes, the same in every language
const EXAMPLE_DOMAIN = 'kinopoisk.ru'
const EXAMPLE_LIST_URL = 'https://example.org/list.txt'
const EXAMPLE_NETWORK = '149.154.160.0/20'

const unixDate = (seconds: number, language: string) => formatDate(new Date(seconds * 1000), 'date-time', language)

/** One rule: the channel, the country of Mysterium, learning, pinned CDNs; every change applies at once. */
const RuleRow = ({ rule }: { rule: DomainRule }) => {
  const setRule = ruleSetMutation.useMutation()
  const removeRule = ruleRemoveMutation.useMutation()
  const [country, setCountry] = useState(rule.country ?? '')
  const t = useT()
  const optional = useOptionalExits()
  const exits = optional.wg
  const busy = setRule.isPending || removeRule.isPending
  const error = setRule.error ?? removeRule.error

  const save = async (change: Partial<DomainRule>) => {
    const next = { ...rule, ...change }
    await setRule.mutateAsync({
      ...next,
      // direct has no exit to keep: a rule switched to it drops sticky
      sticky: next.via !== 'direct' && next.sticky,
      country: next.via === 'dpn' ? next.country : null,
      // a rule switched to wg takes the first exit; the owner picks another in the next cell
      uplink: next.via === 'wg' ? (next.uplink ?? exits.at(0) ?? null) : null,
    })
    await ruleListQuery.refetchQuery()
  }
  const remove = async () => {
    await removeRule.mutateAsync({ domain: rule.domain })
    await ruleListQuery.refetchQuery()
  }

  return (
    <TableRow>
      <TableCell className="font-mono text-sm">{rule.domain}</TableCell>
      <TableCell>
        <XSelect
          options={viaOptions(t, optional)}
          value={rule.via}
          disabled={busy}
          onValueChange={(value) => void save({ via: String(value) as RuleVia })}
        />
      </TableCell>
      <TableCell>
        {rule.via === 'wg' ? (
          <XSelect
            options={exitOptions(exits)}
            value={rule.uplink ?? ''}
            disabled={busy}
            onValueChange={(value) => void save({ uplink: String(value) })}
          />
        ) : (
          <Input
            value={country}
            placeholder={t('rules.anyCountry')}
            maxLength={2}
            className="w-16 uppercase"
            disabled={rule.via !== 'dpn' || busy}
            aria-label={t('rules.exitCountryOf', { domain: rule.domain })}
            onChange={(event) => setCountry(event.target.value.toUpperCase())}
            onBlur={() => {
              const code = country.trim() || null
              if (code !== rule.country && (code === null || code.length === 2)) {
                void save({ country: code })
              }
            }}
          />
        )}
      </TableCell>
      <TableCell>
        <XSwitch
          checked={rule.learn}
          disabled={busy}
          aria-label={t('rules.learnOf', { domain: rule.domain })}
          onCheckedChange={(learn) => void save({ learn })}
        />
      </TableCell>
      <TableCell>
        <XSwitch
          checked={rule.sticky}
          disabled={busy || rule.via === 'direct'}
          aria-label={t('rules.stickyOf', { name: rule.domain })}
          onCheckedChange={(sticky) => void save({ sticky })}
        />
      </TableCell>
      <TableCell className="text-xs">
        {rule.also.map((name) => (
          <button
            key={name}
            type="button"
            className="mr-1 mb-1 font-mono"
            title={t('rules.unpin')}
            disabled={busy}
            onClick={() => void save({ also: rule.also.filter((item) => item !== name) })}
          >
            <Badge variant="secondary">{name} ×</Badge>
          </button>
        ))}
      </TableCell>
      <TableCell>
        <Button
          variant="ghost"
          size="sm"
          loading={removeRule.isPending}
          confirm={t('rules.confirmRemove', { domain: rule.domain })}
          onClick={() => void remove()}
        >
          {t('common.remove')}
        </Button>
        {error && <p className="mt-1 text-xs text-destructive">{error.message}</p>}
      </TableCell>
    </TableRow>
  )
}

const AddRule = () => {
  const setRule = ruleSetMutation.useMutation()
  const [domain, setDomain] = useState('')
  const t = useT()
  const [via, setVia] = useState<RuleVia>('vps')
  const [country, setCountry] = useState('')
  const optional = useOptionalExits()
  const exits = optional.wg
  const [uplink, setUplink] = useState('')
  const add = async () => {
    await setRule.mutateAsync({
      domain,
      via,
      country: via === 'dpn' && country.trim().length === 2 ? country.trim() : null,
      uplink: via === 'wg' ? uplink || exits[0] || null : null,
      sticky: false,
      learn: true,
      also: [],
    })
    setDomain('')
    setCountry('')
    await ruleListQuery.refetchQuery()
  }
  return (
    <div className="mt-4 flex flex-wrap items-center gap-2">
      <Input
        value={domain}
        placeholder={EXAMPLE_DOMAIN}
        className="max-w-xs"
        aria-label={t('rules.site')}
        onChange={(event) => setDomain(event.target.value)}
      />
      <XSelect
        options={viaOptions(t, optional)}
        value={via}
        onValueChange={(value) => setVia(String(value) as RuleVia)}
      />
      {via === 'wg' && (
        <XSelect
          options={exitOptions(exits)}
          value={uplink || exits[0] || ''}
          onValueChange={(value) => setUplink(String(value))}
        />
      )}
      {via === 'dpn' && (
        <Input
          value={country}
          placeholder={t('rules.anyCountry')}
          maxLength={2}
          className="w-16 uppercase"
          aria-label={t('rules.exitCountry')}
          onChange={(event) => setCountry(event.target.value.toUpperCase())}
        />
      )}
      <Button disabled={!domain.trim()} loading={setRule.isPending} onClick={() => void add()}>
        {t('rules.add')}
      </Button>
      {setRule.isError && <p className="w-full text-sm text-destructive">{setRule.error.message}</p>}
    </div>
  )
}

const DomainListRow = ({ item }: { item: DomainListView }) => {
  const remove = domainListRemoveMutation.useMutation()
  const setList = domainListSetMutation.useMutation()
  const t = useT()
  const language = useLanguage()
  const keep = async (sticky: boolean) => {
    await setList.mutateAsync({ url: item.url, via: item.via, country: item.country, uplink: item.uplink, sticky })
    await domainListsQuery.refetchQuery()
  }
  const drop = async () => {
    await remove.mutateAsync({ url: item.url })
    await domainListsQuery.refetchQuery()
  }
  return (
    <TableRow>
      <TableCell className="font-mono text-xs break-all">{item.url}</TableCell>
      <TableCell className="text-sm">{channelText(item, t)}</TableCell>
      <TableCell>
        <XSwitch
          checked={item.sticky}
          disabled={setList.isPending || item.via === 'direct'}
          aria-label={t('rules.stickyOf', { name: item.url })}
          onCheckedChange={(sticky) => void keep(sticky)}
        />
      </TableCell>
      <TableCell className="text-sm">{listCopyText(item, t)}</TableCell>
      <TableCell className="text-xs whitespace-nowrap">
        {item.fetched_at === null ? t('common.none') : unixDate(item.fetched_at, language)}
      </TableCell>
      <TableCell>
        <Button
          variant="ghost"
          size="sm"
          loading={remove.isPending}
          confirm={t('lists.confirmRemove', { url: item.url })}
          onClick={() => void drop()}
        >
          {t('common.remove')}
        </Button>
        {item.error && <p className="mt-1 text-xs text-warning">{item.error}</p>}
        {remove.isError && <p className="mt-1 text-xs text-destructive">{remove.error.message}</p>}
        {setList.isError && <p className="mt-1 text-xs text-destructive">{setList.error.message}</p>}
      </TableCell>
    </TableRow>
  )
}

const AddDomainList = () => {
  const setList = domainListSetMutation.useMutation()
  const [url, setUrl] = useState('')
  const t = useT()
  const [via, setVia] = useState<RuleVia>('vps')
  const [country, setCountry] = useState('')
  const optional = useOptionalExits()
  const exits = optional.wg
  const [uplink, setUplink] = useState('')
  const add = async () => {
    await setList.mutateAsync({
      url,
      via,
      country: via === 'dpn' && country.trim().length === 2 ? country.trim() : null,
      uplink: via === 'wg' ? uplink || exits[0] || null : null,
      sticky: false,
    })
    setUrl('')
    setCountry('')
    await domainListsQuery.refetchQuery()
  }
  return (
    <div className="mt-4 flex flex-wrap items-center gap-2">
      <Input
        value={url}
        placeholder={EXAMPLE_LIST_URL}
        className="max-w-md"
        aria-label={t('lists.url')}
        onChange={(event) => setUrl(event.target.value)}
      />
      <XSelect
        options={viaOptions(t, optional)}
        value={via}
        onValueChange={(value) => setVia(String(value) as RuleVia)}
      />
      {via === 'wg' && (
        <XSelect
          options={exitOptions(exits)}
          value={uplink || exits[0] || ''}
          onValueChange={(value) => setUplink(String(value))}
        />
      )}
      {via === 'dpn' && (
        <Input
          value={country}
          placeholder={t('rules.anyCountry')}
          maxLength={2}
          className="w-16 uppercase"
          aria-label={t('lists.exitCountry')}
          onChange={(event) => setCountry(event.target.value.toUpperCase())}
        />
      )}
      <Button disabled={!url.trim()} loading={setList.isPending} onClick={() => void add()}>
        {t('lists.add')}
      </Button>
      {setList.isError && <p className="w-full text-sm text-destructive">{setList.error.message}</p>}
    </div>
  )
}

const DomainLists = () => {
  const data = domainListsQuery.useQuery().data
  const t = useT()
  if (data?.reason) {
    return <p className="text-muted-foreground">{data.reason}</p>
  }
  const lists = data?.lists ?? []
  return (
    <>
      {lists.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('lists.column.url')}</TableHead>
              <TableHead>{t('lists.column.channel')}</TableHead>
              <TableHead>{t('rules.column.sticky')}</TableHead>
              <TableHead>{t('lists.column.copy')}</TableHead>
              <TableHead>{t('lists.column.fetched')}</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {lists.map((item) => (
              <DomainListRow key={item.url} item={item} />
            ))}
          </TableBody>
        </Table>
      )}
      <AddDomainList />
      <p className="mt-2 text-xs text-muted-foreground">{t('lists.hint')}</p>
    </>
  )
}

const NetworkRow = ({ item }: { item: NetworkRuleView }) => {
  const remove = networkRuleRemoveMutation.useMutation()
  const setNetwork = networkRuleSetMutation.useMutation()
  const t = useT()
  const keep = async (sticky: boolean) => {
    await setNetwork.mutateAsync({
      network: item.network,
      via: item.via,
      country: item.country,
      uplink: item.uplink,
      sticky,
    })
    await networkRulesQuery.refetchQuery()
  }
  const drop = async () => {
    await remove.mutateAsync({ network: item.network })
    await networkRulesQuery.refetchQuery()
  }
  return (
    <TableRow>
      <TableCell className="font-mono text-xs">{item.network}</TableCell>
      <TableCell className="text-sm">{channelText(item, t)}</TableCell>
      <TableCell>
        <XSwitch
          checked={item.sticky}
          disabled={setNetwork.isPending || item.via === 'direct'}
          aria-label={t('rules.stickyOf', { name: item.network })}
          onCheckedChange={(sticky) => void keep(sticky)}
        />
        {setNetwork.isError && <p className="mt-1 text-xs text-destructive">{setNetwork.error.message}</p>}
      </TableCell>
      <TableCell>
        <Button
          variant="ghost"
          size="sm"
          loading={remove.isPending}
          confirm={t('networks.confirmRemove', { network: item.network })}
          onClick={() => void drop()}
        >
          {t('common.remove')}
        </Button>
        {remove.isError && <p className="mt-1 text-xs text-destructive">{remove.error.message}</p>}
      </TableCell>
    </TableRow>
  )
}

const AddNetwork = ({ existing }: { existing: string[] }) => {
  const setNetwork = networkRuleSetMutation.useMutation()
  const t = useT()
  const optional = useOptionalExits()
  const exits = optional.wg
  const [network, setNetworkText] = useState('')
  const [via, setVia] = useState<RuleVia>(optional.tor ? 'tor' : 'vps')
  const [country, setCountry] = useState('')
  const [uplink, setUplink] = useState('')
  const [added, setAdded] = useState<number | null>(null)
  const problem = network.trim() ? networkProblem(network) : null
  const channel = () => ({
    via,
    country: via === 'dpn' && country.trim().length === 2 ? country.trim() : null,
    uplink: via === 'wg' ? uplink || exits[0] || null : null,
    sticky: false,
  })
  const add = async () => {
    await setNetwork.mutateAsync({ network: network.trim(), ...channel() })
    setNetworkText('')
    await networkRulesQuery.refetchQuery()
  }
  // One network after another: core applies each change to the router, and a refusal stops the rest.
  const addTelegram = async () => {
    const missing = TELEGRAM_NETWORKS.filter((item) => !existing.includes(item))
    for (const item of missing) {
      await setNetwork.mutateAsync({ network: item, ...channel() })
    }
    setAdded(missing.length)
    await networkRulesQuery.refetchQuery()
  }
  return (
    <div className="mt-4 space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Input
          value={network}
          placeholder={EXAMPLE_NETWORK}
          className="max-w-xs font-mono"
          aria-label={t('networks.network')}
          onChange={(event) => setNetworkText(event.target.value)}
        />
        <XSelect
          options={viaOptions(t, optional)}
          value={via}
          onValueChange={(value) => setVia(String(value) as RuleVia)}
        />
        {via === 'wg' && (
          <XSelect
            options={exitOptions(exits)}
            value={uplink || exits[0] || ''}
            onValueChange={(value) => setUplink(String(value))}
          />
        )}
        {via === 'dpn' && (
          <Input
            value={country}
            placeholder={t('rules.anyCountry')}
            maxLength={2}
            className="w-16 uppercase"
            aria-label={t('networks.exitCountry')}
            onChange={(event) => setCountry(event.target.value.toUpperCase())}
          />
        )}
        <Button
          disabled={!network.trim() || problem !== null}
          loading={setNetwork.isPending}
          onClick={() => void add()}
        >
          {t('networks.add')}
        </Button>
        <Button variant="outline-secondary" loading={setNetwork.isPending} onClick={() => void addTelegram()}>
          {t('networks.telegram')}
        </Button>
      </div>
      {problem && <p className="text-sm text-warning">{t(`networks.problem.${problem}`)}</p>}
      {added !== null && (
        <p className="text-sm text-muted-foreground">{t('networks.telegramDone', { count: added })}</p>
      )}
      {setNetwork.isError && <p className="text-sm text-destructive">{setNetwork.error.message}</p>}
    </div>
  )
}

const NetworkRules = () => {
  const data = networkRulesQuery.useQuery().data
  const t = useT()
  if (data?.reason) {
    return <p className="text-muted-foreground">{data.reason}</p>
  }
  const networks = data?.networks ?? []
  return (
    <>
      {networks.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('networks.column.network')}</TableHead>
              <TableHead>{t('networks.column.channel')}</TableHead>
              <TableHead>{t('rules.column.sticky')}</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {networks.map((item) => (
              <NetworkRow key={item.network} item={item} />
            ))}
          </TableBody>
        </Table>
      )}
      <AddNetwork existing={networks.map((item) => item.network)} />
      <p className="mt-2 text-xs text-muted-foreground">{t('networks.hint')}</p>
    </>
  )
}

const FollowButton = ({ name, rule }: { name: string; rule: DomainRule }) => {
  const setRule = ruleSetMutation.useMutation()
  const t = useT()
  const follow = async () => {
    await setRule.mutateAsync(withCdn(rule, name))
    await ruleListQuery.refetchQuery()
  }
  return (
    <Button variant="outline-secondary" size="sm" loading={setRule.isPending} onClick={() => void follow()}>
      {t('sniffer.routeLike', { domain: rule.domain })}
    </Button>
  )
}

const Sniffer = ({ client, rules }: { client: string; rules: DomainRule[] }) => {
  const journal = journalQuery.useQuery({ client })
  const t = useT()
  const language = useLanguage()
  const entries: JournalEntry[] = journal.data?.entries ?? []
  const candidates = cdnCandidates(entries, rules)
  const newest = [...entries].sort((a, b) => b.time - a.time).slice(0, SHOWN_QUERIES)
  return (
    <>
      {candidates.length > 0 && (
        <div className="mb-4">
          <h3 className="mb-2 font-accent text-sm text-muted-foreground">{t('sniffer.candidates')}</h3>
          <ul className="space-y-2">
            {candidates.map((candidate) => (
              <li key={candidate.name} className="flex flex-wrap items-center gap-3">
                <span className="font-mono text-sm">{candidate.name}</span>
                <FollowButton name={candidate.name} rule={candidate.rule} />
              </li>
            ))}
          </ul>
        </div>
      )}
      {journal.isError && <p className="text-sm text-destructive">{journal.error.message}</p>}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t('sniffer.column.time')}</TableHead>
            <TableHead>{t('sniffer.column.name')}</TableHead>
            <TableHead>{t('sniffer.column.channel')}</TableHead>
            <TableHead>{t('sniffer.column.addresses')}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {newest.map((entry) => (
            <TableRow key={`${entry.time}-${entry.name}-${entry.qtype}`}>
              <TableCell className="text-xs whitespace-nowrap">{unixDate(entry.time, language)}</TableCell>
              <TableCell className="font-mono text-xs">
                {entry.name} <span className="text-muted-foreground">{entry.qtype}</span>
                {entry.learned_from && (
                  <span className="ml-2 text-success">{t('sniffer.learnedAfter', { site: entry.learned_from })}</span>
                )}
              </TableCell>
              <TableCell className="text-xs">{channelLabel(entry.channel, t)}</TableCell>
              <TableCell className="font-mono text-xs break-all">
                {entry.addresses.join(', ') || t('common.none')}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </>
  )
}

const LearnedRow = ({
  name,
  parent,
  source,
  hits,
  last_seen,
}: {
  name: string
  parent: string
  source: string
  hits: number
  last_seen: number
}) => {
  const forget = learnedForgetMutation.useMutation()
  const t = useT()
  const language = useLanguage()
  const drop = async () => {
    await forget.mutateAsync({ name })
    await learnedListQuery.refetchQuery()
  }
  return (
    <TableRow>
      <TableCell className="font-mono text-xs">{name}</TableCell>
      <TableCell className="font-mono text-xs">{parent}</TableCell>
      <TableCell className="text-xs">{source === 'cname' ? t('learned.how.cname') : t('learned.how.time')}</TableCell>
      <TableCell className="text-xs">{hits}</TableCell>
      <TableCell className="text-xs whitespace-nowrap">{unixDate(last_seen, language)}</TableCell>
      <TableCell>
        <Button variant="ghost" size="sm" loading={forget.isPending} onClick={() => void drop()}>
          {t('learned.forget')}
        </Button>
        {forget.isError && <p className="mt-1 text-xs text-destructive">{forget.error.message}</p>}
      </TableCell>
    </TableRow>
  )
}

/** A section of «Rules» as a card: its description under the title, its content below */
const SectionCard = ({ title, description, children }: { title: string; description: string; children: ReactNode }) => (
  <Card compact h2={title} size="sm">
    <div className="space-y-4 text-sm">
      <p className="text-muted-foreground">{description}</p>
      {children}
    </div>
  </Card>
)

const SitesSection = ({ rules, reason }: { rules: DomainRule[]; reason: string | null }) => {
  const t = useT()
  return (
    <SectionCard title={t('rules.sites.title')} description={t('rules.description')}>
      {reason ? (
        <p className="text-muted-foreground">{reason}</p>
      ) : (
        <>
          <AddRule />
          <p className="text-xs text-muted-foreground">{t('rules.countryRestart')}</p>
          {rules.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('rules.column.site')}</TableHead>
                  <TableHead>{t('rules.column.channel')}</TableHead>
                  <TableHead>{t('rules.column.country')}</TableHead>
                  <TableHead>{t('rules.column.learn')}</TableHead>
                  <TableHead>{t('rules.column.sticky')}</TableHead>
                  <TableHead>{t('rules.column.pinned')}</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {rules.map((rule) => (
                  <RuleRow key={rule.domain} rule={rule} />
                ))}
              </TableBody>
            </Table>
          )}
        </>
      )}
    </SectionCard>
  )
}

const SnifferSection = ({ rules }: { rules: DomainRule[] }) => {
  const devices = journalDevicesQuery.useQuery().data
  const [client, setClient] = useState<string | null>(null)
  const t = useT()
  const deviceOptions = (devices?.devices ?? []).map((device) => ({
    value: device.client,
    label: t('sniffer.deviceOption', { client: device.client, queries: device.queries }),
  }))
  return (
    <SectionCard title={t('sniffer.title')} description={t('sniffer.description')}>
      {devices?.reason ? (
        <p className="text-muted-foreground">{devices.reason}</p>
      ) : deviceOptions.length === 0 ? (
        <p className="text-muted-foreground">{t('sniffer.empty')}</p>
      ) : (
        <>
          <XSelect
            options={deviceOptions}
            value={client ?? ''}
            placeholder={t('sniffer.chooseDevice')}
            onValueChange={(value) => setClient(String(value))}
          />
          {client && <Sniffer client={client} rules={rules} />}
        </>
      )}
    </SectionCard>
  )
}

const LearnedSection = () => {
  const learned = learnedListQuery.useQuery().data
  const t = useT()
  return (
    <SectionCard title={t('learned.title')} description={t('learned.description')}>
      {learned?.reason ? (
        <p className="text-muted-foreground">{learned.reason}</p>
      ) : (learned?.learned.length ?? 0) === 0 ? (
        <p className="text-muted-foreground">{t('learned.empty')}</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('learned.column.name')}</TableHead>
              <TableHead>{t('learned.column.site')}</TableHead>
              <TableHead>{t('learned.column.how')}</TableHead>
              <TableHead>{t('learned.column.hits')}</TableHead>
              <TableHead>{t('learned.column.lastSeen')}</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {learned?.learned.map((item) => (
              <LearnedRow key={item.name} {...item} />
            ))}
          </TableBody>
        </Table>
      )}
    </SectionCard>
  )
}

const Count = ({ value }: { value: number | undefined }) =>
  value === undefined ? null : <Badge variant="secondary">{value}</Badge>

export const rulesPage = generalLayout.lets
  .page('/rules')
  .search(z.object({ section: z.string().optional() }))
  .use(redirectUnauthorizedPlugin)
  .with(ruleListQuery)
  .page(({ data: { rules, reason }, search, setSearch }) => {
    const lists = domainListsQuery.useQuery().data?.lists
    const networks = networkRulesQuery.useQuery().data?.networks
    const learned = learnedListQuery.useQuery().data?.learned
    const t = useT()
    useHead({ title: t('nav.rules') })
    const picked = pickSection(search.section)
    const titles: Record<RuleSection, string> = {
      sites: t('rules.sites.title'),
      lists: t('lists.title'),
      networks: t('networks.title'),
      sniffer: t('sniffer.title'),
      learned: t('learned.title'),
    }
    const counts: Partial<Record<RuleSection, number>> = {
      sites: reason ? undefined : rules.length,
      lists: lists?.length,
      networks: networks?.length,
      learned: learned?.length,
    }
    const detail = (
      <>
        {picked === 'sites' && <SitesSection rules={rules} reason={reason} />}
        {picked === 'lists' && (
          <SectionCard title={titles.lists} description={t('lists.description')}>
            <DomainLists />
          </SectionCard>
        )}
        {picked === 'networks' && (
          <SectionCard title={titles.networks} description={t('networks.description')}>
            <NetworkRules />
          </SectionCard>
        )}
        {picked === 'sniffer' && <SnifferSection rules={rules} />}
        {picked === 'learned' && <LearnedSection />}
      </>
    )
    return (
      <Sections gap="lg">
        <PageTitle title={t('rules.title')} description={t('rules.page.description')} />
        <ListDetail
          label={t('rules.title')}
          items={RULE_SECTIONS.map((section) => ({
            key: section,
            title: titles[section],
            aside: <Count value={counts[section]} />,
          }))}
          picked={picked}
          onPick={(section) => setSearch({ section })}
          detail={detail}
        />
      </Sections>
    )
  })
