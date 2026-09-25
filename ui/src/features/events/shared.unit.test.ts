import { baseStrings, type T } from '@/modules/i18n/base'
import { translate } from '@/modules/i18n/shared'
import { durationText, eventSubject, eventText, eventTone, wifiDrops, type BoxEvent } from '@/features/events/shared'
import { describe, expect, test } from 'bun:test'

const t: T = (key, params) => translate(baseStrings, key, params)
const PHONE = '92:da:e8:fa:f8:63'

const event = (action: BoxEvent['action'], detail: BoxEvent['detail'] = {}, name: string | null = null): BoxEvent => ({
  time: 0,
  kind: action.startsWith('gateway') || action === 'rerouted' ? 'uplink' : 'wifi',
  subject: action.startsWith('gateway') || action === 'rerouted' ? 'dpn' : action.startsWith('ap') ? 'wlp2s0' : PHONE,
  name,
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

  test('a device is shown by name with its MAC, and as unknown when it never told its name', () => {
    expect(eventSubject(event('client_connected', {}, 'realme'), t)).toEqual({ title: 'realme', detail: PHONE })
    expect(eventSubject(event('client_connected'), t)).toEqual({ title: 'Unknown', detail: PHONE })
    expect(eventSubject(event('gateway_silent'), t)).toEqual({ title: 'Uplink dpn', detail: null })
    expect(eventSubject(event('ap_enabled'), t)).toEqual({ title: 'Access point', detail: 'wlp2s0' })
  })

  test('a drop carries the length of the session when core measured it', () => {
    expect(eventText(event('client_disconnected', { session_seconds: 600 }), t)).toBe(
      'Left Wi-Fi after 10 min connected',
    )
    expect(eventText(event('client_disconnected'), t)).toBe('Left Wi-Fi')
    expect(eventText(event('gateway_silent'), t)).toBe('The gateway does not answer')
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

  test('a move along the fallback chain says where the traffic went and warns until it is back', () => {
    expect(eventText(event('rerouted', { through: 'tor' }), t)).toBe('Its traffic goes through tor')
    expect(eventText(event('rerouted', { through: 'direct' }), t)).toBe('Its traffic goes direct')
    expect(eventText(event('rerouted', { through: 'held' }), t)).toBe('Its traffic is held (kill switch)')
    expect(eventTone(event('rerouted', { through: 'tor' }))).toBe('warning')
    expect(eventTone(event('rerouted', { through: 'dpn' }))).toBe('ok')
  })
})
