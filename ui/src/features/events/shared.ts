import type { MessageKey, T } from '@/modules/i18n/base'

export const EVENT_KINDS = ['wifi', 'uplink'] as const
export type EventKind = (typeof EVENT_KINDS)[number]

export type EventAction =
  'client_connected' | 'client_disconnected' | 'ap_enabled' | 'ap_disabled' | 'gateway_answers' | 'gateway_silent'

/** One entry of core's `GET /events` (core/vibedpn/api/models.py: EventView); `time` in unix seconds. */
export type BoxEvent = {
  time: number
  kind: EventKind
  /** a client MAC or the interface for wifi, an uplink key for uplink */
  subject: string
  /** the device name of a client MAC; null when the box knows none */
  name: string | null
  action: EventAction
  detail: Partial<Record<string, number | string>>
}

/** A client of core's `GET /wifi/clients` (core/vibedpn/api/models.py: WifiClientView). */
export type WifiClient = {
  mac: string
  name: string | null
  connected_seconds: number
  signal_dbm: number | null
  inactive_ms: number | null
  rx_bytes: number | null
  tx_bytes: number | null
}

export type EventTone = 'ok' | 'warning'

/** What an event is about, in two lines: a device by name with its MAC under it, the access point, an uplink. */
export type EventSubject = { title: string; detail: string | null }

const MINUTE_SECONDS = 60
export const HOUR_SECONDS = 60 * MINUTE_SECONDS
const DAY_SECONDS = 24 * HOUR_SECONDS
/** Wi-Fi drops within a day from which the status screen asks the owner to look at the journal. */
export const WIFI_DROPS_WARNING = 3
/** The periods of the journal page; the first one is also the window Wi-Fi drops are counted in. */
export const JOURNAL_PERIODS = [
  { hours: 24, label: 'journal.period.day' },
  { hours: 7 * 24, label: 'journal.period.week' },
  { hours: 30 * 24, label: 'journal.period.month' },
] as const satisfies readonly { hours: number; label: MessageKey }[]
export const DROPS_WINDOW_HOURS = JOURNAL_PERIODS[0].hours

/**
 * A length of time in its two largest units that matter: `3 d 4 h`, `2 h 5 min`, `7 min`, `40 s`.
 *
 * @tags events
 */
export const durationText = (seconds: number, t: T): string => {
  const whole = Math.max(0, Math.floor(seconds))
  if (whole >= DAY_SECONDS) {
    return t('duration.days', {
      days: Math.floor(whole / DAY_SECONDS),
      hours: Math.floor((whole % DAY_SECONDS) / HOUR_SECONDS),
    })
  }
  if (whole >= HOUR_SECONDS) {
    return t('duration.hours', {
      hours: Math.floor(whole / HOUR_SECONDS),
      minutes: Math.floor((whole % HOUR_SECONDS) / MINUTE_SECONDS),
    })
  }
  if (whole >= MINUTE_SECONDS) {
    return t('duration.minutes', { minutes: Math.floor(whole / MINUTE_SECONDS) })
  }
  return t('duration.seconds', { seconds: whole })
}

/** A device name, or "unknown" for one that never told it; the MAC is always shown next to it. */
export const deviceName = (name: string | null, t: T): string => name ?? t('device.unknown')

/**
 * Who or what an event is about.
 *
 * @tags events
 */
export const eventSubject = (event: BoxEvent, t: T): EventSubject => {
  if (event.action === 'client_connected' || event.action === 'client_disconnected') {
    return { title: deviceName(event.name, t), detail: event.subject }
  }
  if (event.kind === 'uplink') {
    return { title: t('journal.subject.uplink', { uplink: event.subject }), detail: null }
  }
  return { title: t('journal.subject.accessPoint'), detail: event.subject }
}

/**
 * What happened. Core stores codes and numbers; the sentence is built here, in the current language.
 *
 * @tags events
 */
export const eventText = (event: BoxEvent, t: T): string => {
  switch (event.action) {
    case 'client_connected':
      return t('events.wifi.joined')
    case 'client_disconnected': {
      const session = event.detail.session_seconds
      return typeof session === 'number'
        ? t('events.wifi.leftAfter', { duration: durationText(session, t) })
        : t('events.wifi.left')
    }
    case 'ap_enabled':
      return t('events.ap.up')
    case 'ap_disabled':
      return t('events.ap.down')
    case 'gateway_answers':
      return t('events.uplink.answers')
    case 'gateway_silent':
      return t('events.uplink.silent')
  }
}

/** Something the owner may want to look at: a link lost, not a link gained. */
export const eventTone = (event: BoxEvent): EventTone =>
  event.action === 'client_disconnected' || event.action === 'ap_disabled' || event.action === 'gateway_silent'
    ? 'warning'
    : 'ok'

/** Clients that lost the access point among these events. */
export const wifiDrops = (events: BoxEvent[]): number =>
  events.filter((event) => event.kind === 'wifi' && event.action === 'client_disconnected').length
