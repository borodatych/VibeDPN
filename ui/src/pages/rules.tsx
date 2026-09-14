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
  ruleListQuery,
  ruleRemoveMutation,
  ruleSetMutation,
} from '@/features/rules/api'
import {
  cdnCandidates,
  channelLabel,
  listCopyText,
  withCdn,
  type DomainListView,
  type DomainRule,
  type JournalEntry,
  type RuleVia,
} from '@/features/rules/shared'
import { generalLayout } from '@/layouts/general'
import { redirectUnauthorizedPlugin } from '@/modules/auth/plugins'
import { formatDate } from '@/utils/date'
import { useState } from 'react'

const VIA_OPTIONS = [
  { value: 'vps', label: 'Through the VPS' },
  { value: 'dpn', label: 'Through Mysterium' },
  { value: 'direct', label: 'Direct' },
]

const SHOWN_QUERIES = 100

const unixDate = (seconds: number) => formatDate(new Date(seconds * 1000), 'date-time')

/** One rule: the channel, the country of Mysterium, learning, pinned CDNs; every change applies at once. */
const RuleRow = ({ rule }: { rule: DomainRule }) => {
  const setRule = ruleSetMutation.useMutation()
  const removeRule = ruleRemoveMutation.useMutation()
  const [country, setCountry] = useState(rule.country ?? '')
  const busy = setRule.isPending || removeRule.isPending
  const error = setRule.error ?? removeRule.error

  const save = async (change: Partial<DomainRule>) => {
    const next = { ...rule, ...change }
    await setRule.mutateAsync({ ...next, country: next.via === 'dpn' ? next.country : null })
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
          options={VIA_OPTIONS}
          value={rule.via}
          disabled={busy}
          onValueChange={(value) => void save({ via: String(value) as RuleVia })}
        />
      </TableCell>
      <TableCell>
        <Input
          value={country}
          placeholder="any"
          maxLength={2}
          className="w-16 uppercase"
          disabled={rule.via !== 'dpn' || busy}
          aria-label={`Exit country of ${rule.domain}`}
          onChange={(event) => setCountry(event.target.value.toUpperCase())}
          onBlur={() => {
            const code = country.trim() || null
            if (code !== rule.country && (code === null || code.length === 2)) {
              void save({ country: code })
            }
          }}
        />
      </TableCell>
      <TableCell>
        <XSwitch
          checked={rule.learn}
          disabled={busy}
          aria-label={`Learn the CDNs of ${rule.domain}`}
          onCheckedChange={(learn) => void save({ learn })}
        />
      </TableCell>
      <TableCell className="text-xs">
        {rule.also.map((name) => (
          <button
            key={name}
            type="button"
            className="mr-1 mb-1 font-mono"
            title="Unpin this CDN"
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
          confirm={`Remove the rule of ${rule.domain}?`}
          onClick={() => void remove()}
        >
          Remove
        </Button>
        {error && <p className="mt-1 text-xs text-destructive">{error.message}</p>}
      </TableCell>
    </TableRow>
  )
}

const AddRule = () => {
  const setRule = ruleSetMutation.useMutation()
  const [domain, setDomain] = useState('')
  const [via, setVia] = useState<RuleVia>('vps')
  const [country, setCountry] = useState('')
  const add = async () => {
    await setRule.mutateAsync({
      domain,
      via,
      country: via === 'dpn' && country.trim().length === 2 ? country.trim() : null,
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
        aria-label="Site"
        onChange={(event) => setDomain(event.target.value)}
      />
      <XSelect options={VIA_OPTIONS} value={via} onValueChange={(value) => setVia(String(value) as RuleVia)} />
      {via === 'dpn' && (
        <Input
          value={country}
          placeholder="any"
          maxLength={2}
          className="w-16 uppercase"
          aria-label="Exit country"
          onChange={(event) => setCountry(event.target.value.toUpperCase())}
        />
      )}
      <Button disabled={!domain.trim()} loading={setRule.isPending} onClick={() => void add()}>
        Add rule
      </Button>
      {setRule.isError && <p className="w-full text-sm text-destructive">{setRule.error.message}</p>}
    </div>
  )
}

const VIA_LABELS: Record<RuleVia, string> = { vps: 'VPS', dpn: 'Mysterium', direct: 'direct' }

const DomainListRow = ({ item }: { item: DomainListView }) => {
  const remove = domainListRemoveMutation.useMutation()
  const drop = async () => {
    await remove.mutateAsync({ url: item.url })
    await domainListsQuery.refetchQuery()
  }
  return (
    <TableRow>
      <TableCell className="font-mono text-xs break-all">{item.url}</TableCell>
      <TableCell className="text-sm">
        {VIA_LABELS[item.via]}
        {item.country ? ` ${item.country}` : ''}
      </TableCell>
      <TableCell className="text-sm">{listCopyText(item)}</TableCell>
      <TableCell className="text-xs whitespace-nowrap">
        {item.fetched_at === null ? '—' : unixDate(item.fetched_at)}
      </TableCell>
      <TableCell>
        <Button
          variant="ghost"
          size="sm"
          loading={remove.isPending}
          confirm={`Remove the list ${item.url}?`}
          onClick={() => void drop()}
        >
          Remove
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
  const [via, setVia] = useState<RuleVia>('vps')
  const [country, setCountry] = useState('')
  const add = async () => {
    await setList.mutateAsync({
      url,
      via,
      country: via === 'dpn' && country.trim().length === 2 ? country.trim() : null,
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
        aria-label="List URL"
        onChange={(event) => setUrl(event.target.value)}
      />
      <XSelect options={VIA_OPTIONS} value={via} onValueChange={(value) => setVia(String(value) as RuleVia)} />
      {via === 'dpn' && (
        <Input
          value={country}
          placeholder="any"
          maxLength={2}
          className="w-16 uppercase"
          aria-label="Exit country of the list"
          onChange={(event) => setCountry(event.target.value.toUpperCase())}
        />
      )}
      <Button disabled={!url.trim()} loading={setList.isPending} onClick={() => void add()}>
        Add list
      </Button>
      {setList.isError && <p className="w-full text-sm text-destructive">{setList.error.message}</p>}
    </div>
  )
}

const DomainLists = () => {
  const data = domainListsQuery.useQuery().data
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
              <TableHead>URL</TableHead>
              <TableHead>Channel</TableHead>
              <TableHead>Copy</TableHead>
              <TableHead>Fetched</TableHead>
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
      <p className="mt-2 text-xs text-muted-foreground">
        One domain per line, hosts-file lines or ||domain^; core refreshes a list daily and keeps its last copy. A site
        rule wins over a list.
      </p>
    </>
  )
}

const FollowButton = ({ name, rule }: { name: string; rule: DomainRule }) => {
  const setRule = ruleSetMutation.useMutation()
  const follow = async () => {
    await setRule.mutateAsync(withCdn(rule, name))
    await ruleListQuery.refetchQuery()
  }
  return (
    <Button variant="outline-secondary" size="sm" loading={setRule.isPending} onClick={() => void follow()}>
      Route like {rule.domain}
    </Button>
  )
}

const Sniffer = ({ client, rules }: { client: string; rules: DomainRule[] }) => {
  const journal = journalQuery.useQuery({ client })
  const entries: JournalEntry[] = journal.data?.entries ?? []
  const candidates = cdnCandidates(entries, rules)
  const newest = [...entries].sort((a, b) => b.time - a.time).slice(0, SHOWN_QUERIES)
  return (
    <>
      {candidates.length > 0 && (
        <div className="mb-4">
          <h3 className="mb-2 font-accent text-sm text-muted-foreground">
            CDN candidates: went direct right after a site with a rule
          </h3>
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
            <TableHead>Time</TableHead>
            <TableHead>Name</TableHead>
            <TableHead>Channel</TableHead>
            <TableHead>Addresses</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {newest.map((entry) => (
            <TableRow key={`${entry.time}-${entry.name}-${entry.qtype}`}>
              <TableCell className="text-xs whitespace-nowrap">{unixDate(entry.time)}</TableCell>
              <TableCell className="font-mono text-xs">
                {entry.name} <span className="text-muted-foreground">{entry.qtype}</span>
                {entry.learned_from && <span className="ml-2 text-success">learned after {entry.learned_from}</span>}
              </TableCell>
              <TableCell className="text-xs">{channelLabel(entry.channel)}</TableCell>
              <TableCell className="font-mono text-xs break-all">{entry.addresses.join(', ') || '—'}</TableCell>
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
  const drop = async () => {
    await forget.mutateAsync({ name })
    await learnedListQuery.refetchQuery()
  }
  return (
    <TableRow>
      <TableCell className="font-mono text-xs">{name}</TableCell>
      <TableCell className="font-mono text-xs">{parent}</TableCell>
      <TableCell className="text-xs">{source === 'cname' ? 'CNAME' : 'asked after the site'}</TableCell>
      <TableCell className="text-xs">{hits}</TableCell>
      <TableCell className="text-xs whitespace-nowrap">{unixDate(last_seen)}</TableCell>
      <TableCell>
        <Button variant="ghost" size="sm" loading={forget.isPending} onClick={() => void drop()}>
          Forget
        </Button>
        {forget.isError && <p className="mt-1 text-xs text-destructive">{forget.error.message}</p>}
      </TableCell>
    </TableRow>
  )
}

export const rulesPage = generalLayout.lets
  .page('/rules')
  .head('Rules')
  .use(redirectUnauthorizedPlugin)
  .with(ruleListQuery)
  .page(({ data: { rules, reason } }) => {
    const devices = journalDevicesQuery.useQuery().data
    const learned = learnedListQuery.useQuery().data
    const [client, setClient] = useState<string | null>(null)
    const deviceOptions = (devices?.devices ?? []).map((device) => ({
      value: device.client,
      label: `${device.client} · ${device.queries} queries`,
    }))
    return (
      <Sections gap="lg">
        <Section h1="Rules" description="Each site's channel in smart mode; subdomains and the CDNs it calls follow it">
          {reason ? (
            <p className="text-muted-foreground">{reason}</p>
          ) : (
            <>
              {rules.length > 0 && (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Site</TableHead>
                      <TableHead>Channel</TableHead>
                      <TableHead>Country</TableHead>
                      <TableHead>Learn CDNs</TableHead>
                      <TableHead>Pinned CDNs</TableHead>
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
              <p className="mt-2 text-xs text-muted-foreground">
                A new Mysterium country starts working after `vibedpn restart`.
              </p>
            </>
          )}
        </Section>
        <Section
          h2="Domain lists"
          size="lg"
          description="Ready lists of sites by URL: every domain takes the list's channel"
        >
          <DomainLists />
        </Section>
        <Section h2="Sniffer" size="lg" description="What a device asks, live, and which channel each name took">
          {devices?.reason ? (
            <p className="text-muted-foreground">{devices.reason}</p>
          ) : deviceOptions.length === 0 ? (
            <p className="text-muted-foreground">No DNS queries yet: a device appears once it asks the box a name.</p>
          ) : (
            <>
              <XSelect
                options={deviceOptions}
                value={client ?? ''}
                placeholder="Choose a device"
                onValueChange={(value) => setClient(String(value))}
              />
              <div className="mt-4">{client && <Sniffer client={client} rules={rules} />}</div>
            </>
          )}
        </Section>
        <Section
          h2="Learned CDNs"
          size="lg"
          description="Names that follow their site; forget one and it goes direct again"
        >
          {learned?.reason ? (
            <p className="text-muted-foreground">{learned.reason}</p>
          ) : (learned?.learned.length ?? 0) === 0 ? (
            <p className="text-muted-foreground">Nothing learned yet.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Site</TableHead>
                  <TableHead>How</TableHead>
                  <TableHead>Hits</TableHead>
                  <TableHead>Last seen</TableHead>
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
