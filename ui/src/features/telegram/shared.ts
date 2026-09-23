/** core/vibedpn/config.py Weekday, in the order of the week. */
export const WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'] as const
export type Weekday = (typeof WEEKDAYS)[number]

/** The report schedule of `GET /telegram` (core/vibedpn/api/models.py: TelegramReportView). */
export type TelegramReport = { enabled: boolean; weekday: Weekday; hour: number }

/** The bot of `GET /telegram` (core/vibedpn/api/models.py: TelegramView); its token never comes to the panel. */
export type TelegramBot = {
  enabled: boolean
  token_set: boolean
  /** the bot's username; empty before a token was checked */
  bot: string
  linked: boolean
  /** how the linked chat names itself */
  chat: string
  linked_at: number | null
  /** the link that links a chat, while it waits to be opened */
  link: string | null
  qr_svg: string | null
  link_expires_at: number | null
  alert_after_seconds: number
  timezone: string
  report: TelegramReport
  last_ok: boolean | null
  last_at: number | null
  message: string
  /** the exit of the last message: an uplink key or `direct`; empty when not known */
  via: string
  waiting: number
}

/** core/vibedpn/config.py MIN_ALERT_AFTER_SECONDS and MAX_ALERT_AFTER_SECONDS; core has the last word. */
export const MIN_ALERT_AFTER_SECONDS = 15
export const MAX_ALERT_AFTER_SECONDS = 24 * 3600
/** core/vibedpn/engine/telegram.py DIRECT: the exit of a message that went straight out. */
export const DIRECT = 'direct'
/** core/vibedpn/engine/telegram.py TOKEN_PATTERN: the bot's number, a colon and the secret. */
const TOKEN = /^\d+:[A-Za-z0-9_-]+$/
export const MAX_TOKEN_CHARS = 256
export const HOURS = Array.from({ length: 24 }, (_, hour) => hour)

/**
 * Why this text cannot be a bot token yet; `null` when it can. Only a hint before sending: core checks it again, and
 * Telegram last.
 *
 * @tags telegram
 */
export const tokenProblem = (text: string): 'empty' | 'format' | null => {
  const value = text.trim()
  if (!value) {
    return 'empty'
  }
  return TOKEN.test(value) ? null : 'format'
}

/**
 * Whether a threshold of silence is one core takes: whole seconds within its bounds.
 *
 * @tags telegram
 */
export const alertAfterValid = (seconds: number): boolean =>
  Number.isInteger(seconds) && seconds >= MIN_ALERT_AFTER_SECONDS && seconds <= MAX_ALERT_AFTER_SECONDS

/**
 * The time zone of this browser: most likely the clock of the owner, offered to the report.
 *
 * @tags telegram
 */
export const browserTimeZone = (): string => Intl.DateTimeFormat().resolvedOptions().timeZone
