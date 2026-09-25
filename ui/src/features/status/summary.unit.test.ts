import { raiseInChain, routableUplinks, summarizeStatus, type BoxStatus } from '@/features/status/shared'
import { baseT } from '@/modules/i18n/translator'
import { describe, expect, test } from 'bun:test'

const base: BoxStatus = {
  mode: 'full',
  default_upstream: 'vps',
  failopen: false,
  fallback: [],
  rules_current: true,
  lan_without_exit: false,
  uplinks: [
    {
      name: 'vps',
      enabled: true,
      in_use: true,
      gateway_alive: true,
      checked_at: '2026-09-13T12:00:00Z',
      error: '',
      gateway_route: true,
      kill_switch_route: true,
      lan_access: false,
      exit_through: 'vps',
      fallback: false,
    },
  ],
  dpn: null,
  dpn_countries: [],
}

const withGateway = (alive: boolean | null): BoxStatus => ({
  ...base,
  uplinks: base.uplinks.map((uplink) => ({ ...uplink, gateway_alive: alive })),
})

describe('summarizeStatus', () => {
  test('full through an answering gateway is fine', () => {
    const summary = summarizeStatus(base)
    expect(summary.tone).toBe('ok')
    expect(baseT(summary.headline.key, summary.headline.params)).toBe('The LAN goes out through vps')
  })

  test('the kill switch holding the LAN is the first thing said', () => {
    expect(summarizeStatus({ ...withGateway(false), lan_without_exit: true }).tone).toBe('danger')
  })

  test('a silent gateway with failopen warns that traffic goes direct', () => {
    const summary = summarizeStatus({ ...withGateway(false), failopen: true })
    expect(summary.tone).toBe('warning')
    expect(summary.headline.key).toBe('status.headline.failopen')
  })

  test('a silent gateway whose traffic a fallback carries names that fallback', () => {
    const silent = withGateway(false)
    const summary = summarizeStatus({
      ...silent,
      fallback: ['tor'],
      uplinks: silent.uplinks.map((uplink) => ({ ...uplink, exit_through: 'tor' })),
    })
    expect(summary.tone).toBe('warning')
    expect(baseT(summary.headline.key, summary.headline.params)).toBe(
      'The vps uplink does not answer: the LAN goes out through tor from the fallback chain',
    )
  })

  test('a gateway not probed yet is not called silent', () => {
    expect(summarizeStatus(withGateway(null)).tone).toBe('ok')
  })

  test('rules out of step with config.yaml warn', () => {
    expect(summarizeStatus({ ...base, rules_current: false }).tone).toBe('warning')
  })

  test('smart names the exits its rules use, not default_upstream', () => {
    const uplink = base.uplinks[0]
    const status: BoxStatus = {
      ...base,
      mode: 'smart',
      default_upstream: 'dpn',
      uplinks: [
        { ...uplink, name: 'dpn', in_use: false },
        { ...uplink, name: 'tor', in_use: true },
      ],
    }
    const summary = summarizeStatus(status)
    expect(baseT(summary.headline.key, summary.headline.params)).toBe(
      'Sites by the rules go out through tor, the rest directly',
    )
  })

  test('smart without rules says the LAN goes direct', () => {
    const status: BoxStatus = { ...base, mode: 'smart', uplinks: base.uplinks.map((u) => ({ ...u, in_use: false })) }
    expect(summarizeStatus(status).headline.key).toBe('status.headline.smartNoRules')
  })

  test('mode off says the LAN goes direct', () => {
    expect(summarizeStatus({ ...base, mode: 'off' }).headline.key).toBe('status.headline.direct')
  })
})

describe('the fallback chain', () => {
  test('any enabled uplink may be named but the consumers of rule countries', () => {
    const uplink = base.uplinks[0]
    const status: BoxStatus = {
      ...base,
      uplinks: [
        uplink,
        { ...uplink, name: 'dpn-de' },
        { ...uplink, name: 'wg-second' },
        { ...uplink, name: 'tor', enabled: false },
      ],
    }
    expect(routableUplinks(status)).toEqual(['vps', 'wg-second'])
  })

  test('an uplink moves one place up, the first one stays', () => {
    expect(raiseInChain(['wg-second', 'tor', 'xray'], 'xray')).toEqual(['wg-second', 'xray', 'tor'])
    expect(raiseInChain(['wg-second', 'tor'], 'wg-second')).toEqual(['wg-second', 'tor'])
    expect(raiseInChain(['tor'], 'vps')).toEqual(['tor'])
  })
})
