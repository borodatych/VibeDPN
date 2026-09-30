import { currentChoice, lanOptions, passphraseProblem, SIDECAR, type NetworkView } from '@/features/network/shared'
import { baseT } from '@/modules/i18n/translator'
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
    expect(lanOptions(view(), baseT).map((option) => option.value)).toEqual([SIDECAR, 'wlan0'])
    expect(lanOptions(view(), baseT)[1]?.label).toBe('Gateway: LAN wlan0 192.168.50.1/24, WAN eth0')
  })

  test('shows the saved choice', () => {
    expect(currentChoice(view())).toBe(SIDECAR)
    expect(currentChoice(view({ mode: 'gateway', lan_interface: 'wlan0' }))).toBe('wlan0')
  })
})

describe('passphraseProblem', () => {
  test('takes what hostapd takes, typed twice the same', () => {
    expect(passphraseProblem('my home wifi 2026!', 'my home wifi 2026!')).toBeNull()
    expect(passphraseProblem('x'.repeat(63), 'x'.repeat(63))).toBeNull()
  })

  test('names the first reason it cannot be sent', () => {
    expect(passphraseProblem('short', 'short')).toBe('length')
    expect(passphraseProblem('x'.repeat(64), 'x'.repeat(64))).toBe('length')
    expect(passphraseProblem('пароль-на-русском', 'пароль-на-русском')).toBe('characters')
    expect(passphraseProblem(' padded passphrase', ' padded passphrase')).toBe('spaces')
    expect(passphraseProblem('my home wifi 2026!', 'my home wifi 2025!')).toBe('mismatch')
  })
})
