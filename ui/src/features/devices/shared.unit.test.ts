import { deviceIdent, deviceLabel, matchesSearch, policyOptions, type Device } from '@/features/devices/shared'
import { baseT } from '@/modules/i18n/translator'
import { describe, expect, test } from 'bun:test'

const phone: Device = {
  mac: 'f6:5f:32:9d:fc:41',
  ip: '192.168.1.2',
  name: null,
  hostname: 'phone.lan',
  policy: null,
  seen: true,
  first_seen: '2026-09-13T10:00:00Z',
  last_seen: '2026-09-13T12:00:00Z',
}

const printer: Device = { ...phone, mac: null, ip: '192.168.1.77', hostname: null, name: 'printer', seen: false }

describe('devices', () => {
  test('a device is addressed by MAC, by address without one', () => {
    expect(deviceIdent(phone)).toBe('f6:5f:32:9d:fc:41')
    expect(deviceIdent(printer)).toBe('192.168.1.77')
  })

  test('the own name wins over the PTR name', () => {
    expect(deviceLabel(phone, baseT)).toBe('phone.lan')
    expect(deviceLabel({ ...phone, name: 'Anna phone' }, baseT)).toBe('Anna phone')
  })

  test('a policy through a disabled uplink cannot be chosen', () => {
    const options = policyOptions({ vps: true, dpn: false, tor: false }, baseT)
    expect(options.find((option) => option.value === 'dpn')?.disabled).toBe(true)
    expect(options.find((option) => option.value === 'tor')?.disabled).toBe(true)
    expect(options.find((option) => option.value === 'vps')?.disabled).toBe(false)
    expect(options.map((option) => option.value)).toEqual(['mode', 'vps', 'dpn', 'tor', 'bypass', 'block'])
    expect(policyOptions({ vps: false, dpn: false, tor: true }, baseT).find((o) => o.value === 'tor')?.disabled).toBe(
      false,
    )
  })

  test('search looks at name, host name, MAC and address', () => {
    expect(matchesSearch(phone, 'PHONE')).toBe(true)
    expect(matchesSearch(phone, 'fc:41')).toBe(true)
    expect(matchesSearch(printer, '1.77')).toBe(true)
    expect(matchesSearch(printer, 'tv')).toBe(false)
    expect(matchesSearch(printer, '  ')).toBe(true)
  })
})
