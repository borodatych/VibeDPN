import { format, formatDistanceToNow, isWithinInterval, subHours, type Locale } from 'date-fns'
import { ru } from 'date-fns/locale'

// Date words of a panel language; a language without an entry formats dates in English.
const DATE_LOCALES: Record<string, Locale> = { ru }

export const isDateCanBeRealtive = (date: Date): boolean => {
  const now = new Date()
  return isWithinInterval(date, { start: subHours(now, 48), end: now })
}

export type FormatDateVariant = 'date' | 'date-time' | 'relative' | 'date-nice' | 'date-time-nice'
/**
 * Format every displayed date through here — never inline `date-fns`/`Intl`/`toLocaleString`. Pick a `variant`; the
 * `-nice` variants auto-switch to a relative label for recent dates.
 *
 * @tags rule, util, date
 * @related formatMoney
 */
export const formatDate = (date: Date, variant: FormatDateVariant, language?: string): string => {
  const locale = language ? DATE_LOCALES[language] : undefined
  switch (variant) {
    case 'date':
      return format(date, 'PP', { locale })
    case 'date-time':
      return format(date, 'PP p', { locale })
    case 'relative':
      return formatDistanceToNow(date, { addSuffix: true, locale })
    case 'date-nice':
      return isDateCanBeRealtive(date) ? formatDate(date, 'relative', language) : formatDate(date, 'date', language)
    case 'date-time-nice':
      return isDateCanBeRealtive(date)
        ? formatDate(date, 'relative', language)
        : formatDate(date, 'date-time', language)
  }
}
