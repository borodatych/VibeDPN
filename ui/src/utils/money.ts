/**
 * Format all money through here — never inline `Intl`/`toLocaleString`. Amounts are stored in **minor units** (cents):
 * `amount` is divided by `10 ** decimals`, so pass `1234` to format `$12.34`. Trailing `.00` is trimmed.
 *
 * @example
 *   formatMoney(1234, 'USD') // "$12.34"
 *   formatMoney(1000, 'USD') // "$10"
 *
 * @tags rule, util, money
 * @related formatDate
 */
export const formatMoney = (amount: number, currency: string = 'USD', decimals: number = 2): string => {
  const result = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: currency.toUpperCase(),
  }).format(amount / 10 ** decimals)
  if (result.endsWith('.00')) {
    return result.slice(0, -3)
  }
  return result
}
