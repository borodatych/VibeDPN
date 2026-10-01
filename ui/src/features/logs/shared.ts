import type { ApplyView } from '@/features/uplinks/shared'

/** The lines the host read (core/vibedpn/api/models.py: LogsReportView). */
export type LogsReport = { service: string; tail: number; finished_at: number; text: string }

/** Core's `GET /logs` (core/vibedpn/api/models.py: LogsView). */
export type LogsView = { services: string[]; report: LogsReport | null; state: ApplyView }

/** The numbers of lines offered; core takes from 1 to 1000 (engine/logs.py: MAX_TAIL). */
export const TAIL_CHOICES = [50, 100, 300, 1000] as const
export const DEFAULT_TAIL = 100

/** Which services a page shows the logs of: every one, or those of its own subject. */
export type LogsScope = 'all' | 'uplinks' | 'node' | 'access' | 'network' | 'peers'

const SCOPE_SERVICES: Record<Exclude<LogsScope, 'all' | 'uplinks'>, string[]> = {
  node: ['myst-provider', 'myst-relay'],
  access: ['access'],
  network: ['hostapd', 'dnsmasq', 'adguard'],
  peers: ['wg-server'],
}
const UPLINK_SERVICES = ['tor', 'xray', 'myst-consumer', 'wg-client']
// A WireGuard exit is a gateway of its own, `wg-<name>` (compose.wg.yaml); `wg-server` is the VPS side
const WG_EXIT = /^wg-(?!server$)[a-z0-9-]+$/

const inScope = (service: string, scope: LogsScope): boolean => {
  if (scope === 'all') {
    return true
  }
  if (scope === 'uplinks') {
    return UPLINK_SERVICES.includes(service) || WG_EXIT.test(service)
  }
  return SCOPE_SERVICES[scope].includes(service)
}

/**
 * The services of the box whose logs a page offers, in the order core gave them
 *
 * @tags logs
 */
export const offeredServices = (services: string[], scope: LogsScope): string[] =>
  services.filter((service) => inScope(service, scope))
