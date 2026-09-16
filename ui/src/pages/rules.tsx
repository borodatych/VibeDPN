import { useHead } from '@unhead/react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Section, Sections } from '@/components/ui/section'
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
  type RuleVia,
} from '@/features/rules/shared'
import { boxStatusQuery } from '@/features/status/api'
import { generalLayout } from '@/layouts/general'
import { redirectUnauthorizedPlugin } from '@/modules/auth/plugins'
import type { T } from '@/modules/i18n/base'
import { useLanguage, useT } from '@/modules/i18n/use-t'
import { formatDate } from '@/utils/date'
import { useState } from 'react'

const viaOptions = (t: T, exits: string[], tor: boolean) => [
  { value: 'vps', label: t('rules.via.vps') },
  { value: 'dpn', label: t('rules.via.dpn') },
  // a WireGuard exit is offered only when the box has one, Tor only when it is on
  ...(exits.length > 0 ? [{ value: 'wg', label: t('rules.via.wg') }] : []),
  ...(tor ? [{ value: 'tor', label: t('rules.via.tor') }] : []),
  { value: 'direct', label: t('rules.via.direct') },
]

const exitOptions = (exits: string[]) => exits.map((name) => ({ value: name, label: name }))

/** The named WireGuard exits of the box, for the channel choice of rules and lists. */
const useWgExits = () => wgExitNames(boxStatusQuery.useQuery().data?.status.uplinks ?? [])

/** Whether uplink tor is on, for the channel choice of rules and lists. */
const useTorEnabled = () =>
  (boxStatusQuery.useQuery().data?.status.uplinks ?? []).some((uplink) => uplink.name === 'tor' && uplink.enabled)

const SHOWN_QUERIES = 100

const unixDate = (seconds: number, language: string) => formatDate(new Date(seconds * 1000), 'date-time', language)

/** One rule: the channel, the country of Mysterium, learning, pinned CDNs; every change applies at once. */
const RuleRow = ({ rule }: { rule: DomainRule }) => {
  const setRule = ruleSetMutation.useMutation()
  const removeRule = ruleRemoveMutation.useMutation()
  const [country, setCountry] = useState(rule.country ?? '')
  const t = useT()
  const exits = useWgExits()
  const torEnabled = useTorEnabled()
  const busy = setRule.isPending || removeRule.isPending
  const error = setRule.error ?? removeRule.error

  const save = async (change: Partial<DomainRule>) => {
    const next = { ...rule, ...change }
    await setRule.mutateAsync({
      ...next,
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
          options={viaOptions(t, exits, torEnabled)}
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
  const exits = useWgExits()
  const torEnabled = useTorEnabled()
  const [uplink, setUplink] = useState('')
  const add = async () => {
    await setRule.mutateAsync({
      domain,
      via,
      country: via === 'dpn' && country.trim().length === 2 ? country.trim() : null,
      uplink: via === 'wg' ? uplink || exits[0] || null : null,
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
        placeholder="kinopoisk.ru"
        className="max-w-xs"
        aria-label={t('rules.site')}
        onChange={(event) => setDomain(event.target.value)}
      />
      <XSelect
        options={viaOptions(t, exits, torEnabled)}
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
  const t = useT()
  const language = useLanguage()
  const drop = async () => {
    await remove.mutateAsync({ url: item.url })
    await domainListsQuery.refetchQuery()
  }
  return (
    <TableRow>
      <TableCell className="font-mono text-xs break-all">{item.url}</TableCell>
      <TableCell className="text-sm">{channelText(item, t)}</TableCell>
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
  const exits = useWgExits()
  const torEnabled = useTorEnabled()
  const [uplink, setUplink] = useState('')
  const add = async () => {
    await setList.mutateAsync({
      url,
      via,
      country: via === 'dpn' && country.trim().length === 2 ? country.trim() : null,
      uplink: via === 'wg' ? uplink || exits[0] || null : null,
    })
    setUrl('')
    setCountry('')
    await domainListsQuery.refetchQuery()
  }
  return (
    <div className="mt-4 flex flex-wrap items-center gap-2">
      <Input
        value={url}
        placeholder="https://example.org/list.txt"
        className="max-w-md"
        aria-label={t('lists.url')}
        onChange={(event) => setUrl(event.target.value)}
      />
      <XSelect
        options={viaOptions(t, exits, torEnabled)}
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
  const t = useT()
  const drop = async () => {
    await remove.mutateAsync({ network: item.network })
    await networkRulesQuery.refetchQuery()
  }
  return (
    <TableRow>
      <TableCell className="font-mono text-xs">{item.network}</TableCell>
      <TableCell className="text-sm">{channelText(item, t)}</TableCell>
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
  const exits = useWgExits()
  const torEnabled = useTorEnabled()
  const [network, setNetworkText] = useState('')
  const [via, setVia] = useState<RuleVia>(torEnabled ? 'tor' : 'vps')
  const [country, setCountry] = useState('')
  const [uplink, setUplink] = useState('')
  const [added, setAdded] = useState<number | null>(null)
  const problem = network.trim() ? networkProblem(network) : null
  const channel = () => ({
    via,
    country: via === 'dpn' && country.trim().length === 2 ? country.trim() : null,
    uplink: via === 'wg' ? uplink || exits[0] || null : null,
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
          placeholder="149.154.160.0/20"
          className="max-w-xs font-mono"
          aria-label={t('networks.network')}
          onChange={(event) => setNetworkText(event.target.value)}
        />
        <XSelect
          options={viaOptions(t, exits, torEnabled)}
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

export const rulesPage = generalLayout.lets
  .page('/rules')
  .use(redirectUnauthorizedPlugin)
  .with(ruleListQuery)
  .page(({ data: { rules, reason } }) => {
    const devices = journalDevicesQuery.useQuery().data
    const learned = learnedListQuery.useQuery().data
    const [client, setClient] = useState<string | null>(null)
    const t = useT()
    useHead({ title: t('nav.rules') })
    const deviceOptions = (devices?.devices ?? []).map((device) => ({
      value: device.client,
      label: t('sniffer.deviceOption', { client: device.client, queries: device.queries }),
    }))
    return (
      <Sections gap="lg">
        <Section h1={t('rules.title')} description={t('rules.description')}>
          {reason ? (
            <p className="text-muted-foreground">{reason}</p>
          ) : (
            <>
              {rules.length > 0 && (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t('rules.column.site')}</TableHead>
                      <TableHead>{t('rules.column.channel')}</TableHead>
                      <TableHead>{t('rules.column.country')}</TableHead>
                      <TableHead>{t('rules.column.learn')}</TableHead>
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
              <AddRule />
              <p className="mt-2 text-xs text-muted-foreground">{t('rules.countryRestart')}</p>
            </>
          )}
        </Section>
        <Section h2={t('lists.title')} size="lg" description={t('lists.description')}>
          <DomainLists />
        </Section>
        <Section h2={t('networks.title')} size="lg" description={t('networks.description')}>
          <NetworkRules />
        </Section>
        <Section h2={t('sniffer.title')} size="lg" description={t('sniffer.description')}>
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
              <div className="mt-4">{client && <Sniffer client={client} rules={rules} />}</div>
            </>
          )}
        </Section>
        <Section h2={t('learned.title')} size="lg" description={t('learned.description')}>
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
        </Section>
      </Sections>
    )
  })
