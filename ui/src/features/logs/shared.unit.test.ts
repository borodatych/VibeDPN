import { offeredServices } from '@/features/logs/shared'
import { describe, expect, test } from 'bun:test'

describe('logs of a page', () => {
  const services = [
    'access',
    'adguard',
    'core',
    'hostapd',
    'myst-provider',
    'tor',
    'wg-client',
    'wg-home2',
    'wg-server',
  ]

  test('the status page offers every service of the box', () => {
    expect(offeredServices(services, 'all')).toEqual(services)
  })

  test('the exits are the gateways, WireGuard ones by their own name, not the server of a VPS', () => {
    expect(offeredServices(services, 'uplinks')).toEqual(['tor', 'wg-client', 'wg-home2'])
    expect(offeredServices(services, 'peers')).toEqual(['wg-server'])
  })

  test('a page offers only what the box runs', () => {
    expect(offeredServices(services, 'network')).toEqual(['adguard', 'hostapd'])
    expect(offeredServices(['core'], 'access')).toEqual([])
  })
})
