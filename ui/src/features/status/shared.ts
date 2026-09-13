/** The answer of core's `GET /status` (core/vibedpn/api/models.py: BoxStatus). */
export type UplinkStatus = {
  name: 'vps' | 'dpn'
  enabled: boolean
  in_use: boolean
  gateway_alive: boolean | null
  checked_at: string | null
  error: string
  gateway_route: boolean | null
  kill_switch_route: boolean | null
}

export type BoxStatus = {
  mode: 'off' | 'full' | 'smart'
  default_upstream: 'vps' | 'dpn'
  failopen: boolean
  rules_current: boolean | null
  lan_without_exit: boolean
  uplinks: UplinkStatus[]
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
