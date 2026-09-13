import { format, formatDistanceToNow, isWithinInterval, subHours } from 'date-fns'

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
export const formatDate = (date: Date, variant: FormatDateVariant): string => {
  switch (variant) {
    case 'date':
      return format(date, 'PP')
    case 'date-time':
      return format(date, 'PP p')
    case 'relative':
      return formatDistanceToNow(date, { addSuffix: true })
    case 'date-nice':
      return isDateCanBeRealtive(date) ? formatDate(date, 'relative') : formatDate(date, 'date')
    case 'date-time-nice':
      return isDateCanBeRealtive(date) ? formatDate(date, 'relative') : formatDate(date, 'date-time')
  }
}
