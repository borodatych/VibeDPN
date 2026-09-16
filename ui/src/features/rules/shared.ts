import type { T } from '@/modules/i18n/base'

/** One domain rule of core's `GET /rules` (core/vibedpn/api/models.py: DomainRuleView). */
export type DomainRule = {
  domain: string
  via: RuleVia
  country: string | null
  /** via wg: the name of the exit in upstreams.wg */
  uplink: string | null
  learn: boolean
  also: string[]
}

export type RuleVia = 'vps' | 'dpn' | 'wg' | 'tor' | 'direct'

export const RULE_VIAS = ['vps', 'dpn', 'wg', 'tor', 'direct'] as const

const WG_KEY_PREFIX = 'wg-'

/**
 * The named WireGuard exits of the box, from the uplink keys of `GET /status` (`wg-<name>`).
 *
 * @tags rules
 */
export const wgExitNames = (uplinks: { name: string }[]): string[] =>
  uplinks
    .map((uplink) => uplink.name)
    .filter((name) => name.startsWith(WG_KEY_PREFIX))
    .map((name) => name.slice(WG_KEY_PREFIX.length))
    .sort()

/** The channel of a rule or a list as the owner reads it: `Mysterium DE`, `WireGuard proton`, `VPS`. */
export const channelText = (item: { via: RuleVia; country: string | null; uplink: string | null }, t: T): string => {
  if (item.via === 'dpn' && item.country) {
    return t('rules.channel.dpnCountry', { country: item.country })
  }
  if (item.via === 'wg' && item.uplink) {
    return t('rules.channel.wg', { uplink: item.uplink })
  }
  return t(`rules.channel.${item.via}`)
}

/** One DNS query of a device from `GET /dns/journal/{client}`; `time` in unix seconds. */
export type JournalEntry = {
  time: number
  name: string
  qtype: string
  cached: boolean
  addresses: string[]
  /** smart_* set of the rule the name went through, or `direct` */
  channel: string
  /** this query taught the name to follow that site */
  learned_from: string | null
}

export type JournalDevice = { client: string; queries: number }

/** A name of `GET /learned`: it follows its parent site. */
export type LearnedName = {
  name: string
  parent: string
  source: 'time' | 'cname'
  first_seen: number
  last_seen: number
  hits: number
}

export const DIRECT_CHANNEL = 'direct'
// core/vibedpn/engine/learning.py WINDOW_SECONDS: a CDN is asked within this after its site
export const CDN_WINDOW_SECONDS = 10

const bare = (name: string) => name.toLowerCase().replace(/\.$/, '')

/**
 * The rule a name falls under: the rule of the name itself or of its closest parent domain (a rule covers subdomains).
 *
 * @tags rules
 */
export const ruleOf = (name: string, rules: DomainRule[]): DomainRule | null => {
  const labels = bare(name).split('.')
  for (let start = 0; start < labels.length - 1; start += 1) {
    const suffix = labels.slice(start).join('.')
    const rule = rules.find((item) => item.domain === suffix || item.also.includes(suffix))
    if (rule) {
      return rule
    }
  }
  return null
}

export type CdnCandidate = { name: string; rule: DomainRule; lastAsked: number }

/**
 * Names that went direct right after a site under a rule: the CDNs that site probably calls. Core learns them itself
 * when the rule learns; the owner sees the rest here and sends them after the site. Newest first, one per name.
 *
 * @tags rules
 */
export const cdnCandidates = (entries: JournalEntry[], rules: DomainRule[]): CdnCandidate[] => {
  const ordered = [...entries].sort((a, b) => a.time - b.time)
  const found = new Map<string, CdnCandidate>()
  let lastSite: { rule: DomainRule; time: number } | null = null
  for (const entry of ordered) {
    const rule = ruleOf(entry.name, rules)
    if (rule) {
      lastSite = { rule, time: entry.time }
      continue
    }
    if (entry.channel !== DIRECT_CHANNEL || !lastSite || entry.time - lastSite.time > CDN_WINDOW_SECONDS) {
      continue
    }
    found.set(bare(entry.name), { name: bare(entry.name), rule: lastSite.rule, lastAsked: entry.time })
  }
  return [...found.values()].sort((a, b) => b.lastAsked - a.lastAsked)
}

/** The rule with a CDN pinned after its site; a name already pinned leaves it as it is. */
export const withCdn = (rule: DomainRule, name: string): DomainRule =>
  rule.also.includes(bare(name)) ? rule : { ...rule, also: [...rule.also, bare(name)] }

/** A human label of a channel: `smart_vps` → `VPS`, `smart_dpn_de` → `Mysterium DE`. */
export const channelLabel = (channel: string, t: T): string => {
  if (channel === DIRECT_CHANNEL) {
    return t('rules.channel.direct')
  }
  if (channel === 'smart_vps') {
    return t('rules.channel.vps')
  }
  if (channel === 'smart_tor') {
    return t('rules.channel.tor')
  }
  // core spells '-' of an exit name as '_' in the set name; a name never holds '_' itself
  const wg = /^smart_wg_(\w+)$/.exec(channel)
  if (wg) {
    return t('rules.channel.wg', { uplink: wg[1].replaceAll('_', '-') })
  }
  const dpn = /^smart_dpn_(\w+)$/.exec(channel)
  if (dpn) {
    return dpn[1] === 'any' ? t('rules.channel.dpn') : t('rules.channel.dpnCountry', { country: dpn[1].toUpperCase() })
  }
  return channel === 'smart_direct' ? t('rules.channel.ruleDirect') : channel
}

/** One network rule of `GET /networks` (core/vibedpn/api/models.py: NetworkRuleView). */
export type NetworkRuleView = { network: string; via: RuleVia; country: string | null; uplink: string | null }

/**
 * The IPv4 networks Telegram publishes for its apps (https://core.telegram.org/resources/cidr.txt, taken 2026-09-17);
 * the app connects to these addresses without asking for names, so only network rules catch it.
 */
export const TELEGRAM_NETWORKS = [
  '91.108.56.0/22',
  '91.108.4.0/22',
  '91.108.8.0/22',
  '91.108.16.0/22',
  '91.108.12.0/22',
  '149.154.160.0/20',
  '91.105.192.0/23',
  '91.108.20.0/22',
  '185.76.151.0/24',
] as const

const IPV4_NETWORK = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\/(\d{1,2})$/
const OCTET_MAX = 255
const PREFIX_MAX = 32
const OCTET_BITS = 8

/**
 * Why a text is not an IPv4 network core takes (`a.b.c.d/nn`, host bits zero), or null when it is. Only a hint before
 * sending: core checks the network itself.
 *
 * @tags rules
 */
export const networkProblem = (text: string): 'format' | 'hostBits' | null => {
  const match = IPV4_NETWORK.exec(text.trim())
  if (!match) {
    return 'format'
  }
  const octets = match.slice(1, 5).map(Number)
  const prefix = Number(match[5])
  if (octets.some((octet) => octet > OCTET_MAX) || prefix > PREFIX_MAX) {
    return 'format'
  }
  const address = octets.reduce((value, octet) => value * 2 ** OCTET_BITS + octet, 0)
  const hostSize = 2 ** (PREFIX_MAX - prefix)
  return address % hostSize === 0 ? null : 'hostBits'
}

/** One ready list of `GET /lists` (core/vibedpn/api/models.py: DomainListView). */
export type DomainListView = {
  url: string
  via: RuleVia
  country: string | null
  uplink: string | null
  /** 0 until core has a first copy */
  domains: number
  /** unix seconds of the copy in use */
  fetched_at: number | null
  /** why the copy in use is not newer, or why there is none */
  error: string
}

/**
 * What the owner reads about the copy of a list core uses.
 *
 * @tags rules
 */
export const listCopyText = (item: DomainListView, t: T): string => {
  if (item.fetched_at === null) {
    return item.error ? t('lists.copy.none') : t('lists.copy.fetching')
  }
  return t('lists.copy.domains', { count: item.domains })
}
