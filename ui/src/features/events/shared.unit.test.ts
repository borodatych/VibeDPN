import { baseStrings, type T } from '@/modules/i18n/base'
import { translate } from '@/modules/i18n/shared'
import { deviceNames, durationText, eventText, eventTone, wifiDrops, type BoxEvent } from '@/features/events/shared'
import { describe, expect, test } from 'bun:test'

const t: T = (key, params) => translate(baseStrings, key, params)
const PHONE = '92:da:e8:fa:f8:63'

const event = (action: BoxEvent['action'], detail: BoxEvent['detail'] = {}): BoxEvent => ({
  time: 0,
  kind: action.startsWith('gateway') ? 'uplink' : 'wifi',
  subject: action.startsWith('gateway') ? 'dpn' : PHONE,
  action,
  detail,
})

describe('events', () => {
  test('a duration keeps the two units that matter', () => {
    expect(durationText(40, t)).toBe('40 s')
    expect(durationText(420, t)).toBe('7 min')
    expect(durationText(54_572, t)).toBe('15 h 9 min')
    expect(durationText(3 * 86_400 + 4 * 3600 + 59, t)).toBe('3 d 4 h')
  })

  test('a client is named when the box knows it, by its MAC otherwise', () => {
    const names = deviceNames([
      { mac: PHONE, name: null, hostname: 'phone' },
      { mac: 'aa:bb:cc:dd:ee:01', name: 'Laptop', hostname: 'laptop-7' },
      { mac: null, name: 'By address', hostname: null },
    ])
    expect(names).toEqual({ [PHONE]: 'phone', 'aa:bb:cc:dd:ee:01': 'Laptop' })
    expect(eventText(event('client_connected'), t, names)).toBe('phone — joined Wi-Fi')
    expect(eventText(event('client_connected'), t, {})).toBe(`${PHONE} — joined Wi-Fi`)
  })

  test('a drop carries the length of the session when core measured it', () => {
    expect(eventText(event('client_disconnected', { session_seconds: 600 }), t, {})).toBe(
      `${PHONE} — left Wi-Fi after 10 min connected`,
    )
    expect(eventText(event('client_disconnected'), t, {})).toBe(`${PHONE} — left Wi-Fi`)
    expect(eventText(event('gateway_silent'), t, {})).toBe('Uplink dpn: the gateway does not answer')
  })

  test('losses stand out and only client drops are counted', () => {
    expect(eventTone(event('client_disconnected'))).toBe('warning')
    expect(eventTone(event('gateway_silent'))).toBe('warning')
    expect(eventTone(event('client_connected'))).toBe('ok')
    expect(
      wifiDrops([
        event('client_disconnected'),
        event('client_connected'),
        event('gateway_silent'),
        event('client_disconnected'),
      ]),
    ).toBe(2)
  })
})
