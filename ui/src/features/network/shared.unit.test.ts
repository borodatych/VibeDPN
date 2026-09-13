import { currentChoice, lanOptions, SIDECAR, type NetworkView } from '@/features/network/shared'
import { describe, expect, test } from 'bun:test'

const view = (patch: Partial<NetworkView> = {}): NetworkView => ({
  mode: 'sidecar',
  lan_interface: 'eth0',
  lan_address: '192.168.1.50',
  wan_interface: null,
  restart_required: false,
  interfaces: [
    { name: 'eth0', address: '192.168.1.50', prefixlen: 24, default_route: true },
    { name: 'wlan0', address: '192.168.50.1', prefixlen: 24, default_route: false },
  ],
  ...patch,
})

describe('lanOptions', () => {
  test('offers one port on the default-route interface and every other one as a gateway LAN', () => {
    expect(lanOptions(view()).map((option) => option.value)).toEqual([SIDECAR, 'wlan0'])
    expect(lanOptions(view())[1]?.label).toBe('Gateway: LAN wlan0 192.168.50.1/24, WAN eth0')
  })

  test('shows the saved choice', () => {
    expect(currentChoice(view())).toBe(SIDECAR)
    expect(currentChoice(view({ mode: 'gateway', lan_interface: 'wlan0' }))).toBe('wlan0')
  })
})
