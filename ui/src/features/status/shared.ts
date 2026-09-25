import type { MessageKey } from '@/modules/i18n/base'
import type { Params } from '@/modules/i18n/shared'

/** The answer of core's `GET /status` (core/vibedpn/api/models.py: BoxStatus). */
export type UplinkStatus = {
  /** vps, dpn, dpn-<country> for the consumer of a rule country, or wg-<name> for a named WireGuard exit */
  name: string
  enabled: boolean
  in_use: boolean
  gateway_alive: boolean | null
  checked_at: string | null
  error: string
  gateway_route: boolean | null
  kill_switch_route: boolean | null
  lan_access: boolean | null
  /** an uplink in use: the uplink whose gateway carries its traffic on the host now (itself or a fallback); null: none */
  exit_through: string | null
  /** it is in routing.fallback */
  fallback: boolean
}

/** A Mysterium consumer as core last saw it: the one of uplink dpn or of a rule country. */
export type DpnStatus = {
  identity: string | null
  registration: string
  connection: string
  country: string | null
  error: string
  balance_wei: string
  channel_address: string
}

/** One country of `GET /dpn/countries`; prices in wei of MYST. */
export type DpnCountry = {
  country: string
  nodes: number
  min_per_hour_wei: string
  min_per_gib_wei: string
}

export type BoxStatus = {
  mode: 'off' | 'full' | 'smart'
  /** an uplink key: vps, dpn, or wg-<name> of a named WireGuard exit */
  default_upstream: string
  failopen: boolean
  /** routing.fallback in order: the uplinks that take the traffic of a silent one */
  fallback: string[]
  rules_current: boolean | null
  lan_without_exit: boolean
  uplinks: UplinkStatus[]
  dpn: DpnStatus | null
  /** consumers of the exit countries of domain rules, one per country */
  dpn_countries: DpnStatus[]
}

/** The answer of core's `PUT /routing`. */
export type RoutingView = {
  mode: string
  default_upstream: string
  fallback: string[]
  adguard: 'applied' | 'pending' | 'none'
}

export type StatusTone = 'ok' | 'warning' | 'danger'

/** A phrase of the catalog with its values: the screen translates it. */
export type Phrase = { key: MessageKey; params?: Params }

/**
 * One line the owner reads first. Pure: it names the phrase and its tone, the screen says it in the current language.
 *
 * @tags status
 */
export const summarizeStatus = (status: BoxStatus): { tone: StatusTone; headline: Phrase } => {
  const uplink = status.default_upstream
  if (status.lan_without_exit) {
    return { tone: 'danger', headline: { key: 'status.headline.noExit', params: { uplink } } }
  }
  const modeUplink = status.uplinks.find((item) => item.name === status.default_upstream)
  if (status.mode === 'full' && modeUplink?.gateway_alive === false) {
    const through = modeUplink.exit_through
    if (through !== null && through !== uplink) {
      return { tone: 'warning', headline: { key: 'status.headline.fallback', params: { uplink, through } } }
    }
    return { tone: 'warning', headline: { key: 'status.headline.failopen', params: { uplink } } }
  }
  if (status.rules_current === false) {
    return { tone: 'warning', headline: { key: 'status.headline.rulesDiffer' } }
  }
  if (status.mode === 'off') {
    return { tone: 'ok', headline: { key: 'status.headline.direct' } }
  }
  if (status.mode === 'smart') {
    // smart has no exit of its own: the rules name theirs, and default_upstream carries nothing
    const used = status.uplinks
      .filter((item) => item.in_use && !item.name.startsWith(COUNTRY_KEY_PREFIX))
      .map((item) => item.name)
    return used.length === 0
      ? { tone: 'ok', headline: { key: 'status.headline.smartNoRules' } }
      : { tone: 'ok', headline: { key: 'status.headline.smart', params: { uplinks: used.join(', ') } } }
  }
  return { tone: 'ok', headline: { key: 'status.headline.through', params: { uplink } } }
}

/** A consumer of a rule country (dpn-<country>) serves its rules only: no mode and no chain goes through it. */
const COUNTRY_KEY_PREFIX = 'dpn-'

/**
 * The uplinks the owner may name as the exit of the LAN or in the fallback chain: the enabled ones but the rule
 * countries.
 *
 * @tags status
 */
export const routableUplinks = (status: BoxStatus): string[] =>
  status.uplinks
    .filter((uplink) => uplink.enabled && !uplink.name.startsWith(COUNTRY_KEY_PREFIX))
    .map((uplink) => uplink.name)

/**
 * The fallback chain with one uplink moved a place up; the first one stays where it is.
 *
 * @tags status
 */
export const raiseInChain = (chain: string[], name: string): string[] => {
  const index = chain.indexOf(name)
  if (index <= 0) {
    return chain
  }
  const next = [...chain]
  next.splice(index - 1, 2, name, chain[index - 1])
  return next
}

/** `GET /dpn/registration` (core/vibedpn/api/models.py: DpnRegistrationView): the price before the click. */
export type DpnRegistration = {
  identity: string
  status: string
  free: boolean
  fee_wei: string
  balance_wei: string
  channel_address: string
  affordable: boolean
}

/** core/vibedpn/engine/consumer.py REGISTERED: the word the node uses for a done registration. */
export const REGISTERED = 'Registered'
