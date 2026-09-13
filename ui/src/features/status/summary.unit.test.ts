import { summarizeStatus, type BoxStatus } from '@/features/status/shared'
import { describe, expect, test } from 'bun:test'

const base: BoxStatus = {
  mode: 'full',
  default_upstream: 'vps',
  failopen: false,
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
    },
  ],
}

const withGateway = (alive: boolean | null): BoxStatus => ({
  ...base,
  uplinks: base.uplinks.map((uplink) => ({ ...uplink, gateway_alive: alive })),
})

describe('summarizeStatus', () => {
  test('full through an answering gateway is fine', () => {
    expect(summarizeStatus(base)).toEqual({ tone: 'ok', headline: 'The LAN goes out through vps' })
  })

  test('the kill switch holding the LAN is the first thing said', () => {
    expect(summarizeStatus({ ...withGateway(false), lan_without_exit: true }).tone).toBe('danger')
  })

  test('a silent gateway with failopen warns that traffic goes direct', () => {
    const summary = summarizeStatus({ ...withGateway(false), failopen: true })
    expect(summary.tone).toBe('warning')
    expect(summary.headline).toContain('directly')
  })

  test('a gateway not probed yet is not called silent', () => {
    expect(summarizeStatus(withGateway(null)).tone).toBe('ok')
  })

  test('rules out of step with config.yaml warn', () => {
    expect(summarizeStatus({ ...base, rules_current: false }).tone).toBe('warning')
  })

  test('mode off says the LAN goes direct', () => {
    expect(summarizeStatus({ ...base, mode: 'off' }).headline).toContain('directly')
  })
})
