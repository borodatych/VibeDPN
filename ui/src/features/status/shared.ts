/** The answer of core's `GET /status` (core/vibedpn/api/models.py: BoxStatus). */
export type UplinkStatus = {
  /** vps, dpn, or dpn-<country> for the consumer of a rule country */
  name: string
  enabled: boolean
  in_use: boolean
  gateway_alive: boolean | null
  checked_at: string | null
  error: string
  gateway_route: boolean | null
  kill_switch_route: boolean | null
  lan_access: boolean | null
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
  default_upstream: 'vps' | 'dpn'
  failopen: boolean
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
  adguard: 'applied' | 'pending' | 'none'
}

export type StatusTone = 'ok' | 'warning' | 'danger'

/**
 * One line the owner reads first. Pure: the screen renders it, the unit test pins it.
 *
 * @tags status
 */
export const summarizeStatus = (status: BoxStatus): { tone: StatusTone; headline: string } => {
  if (status.lan_without_exit) {
    return {
      tone: 'danger',
      headline: `No internet for the LAN: the ${status.default_upstream} uplink does not answer and the kill switch holds traffic`,
    }
  }
  const modeUplink = status.uplinks.find((uplink) => uplink.name === status.default_upstream)
  if (status.mode === 'full' && modeUplink?.gateway_alive === false) {
    return {
      tone: 'warning',
      headline: `The ${status.default_upstream} uplink does not answer: the LAN goes out directly (failopen)`,
    }
  }
  if (status.rules_current === false) {
    return { tone: 'warning', headline: 'The router rules differ from config.yaml: restart the box' }
  }
  if (status.mode === 'off') {
    return { tone: 'ok', headline: 'The LAN goes out directly; devices with their own policy keep it' }
  }
  return { tone: 'ok', headline: `The LAN goes out through ${status.default_upstream}` }
}
