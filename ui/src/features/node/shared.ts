/** The answer of core's `GET /provider/stats` (core/vibedpn/engine/myst.py: ProviderStats). */
export type Tokens = { wei: string; human: string }

export type NodeStats = {
  node_version: string
  node_uptime: string
  monitoring_status: string
  identity: {
    id: string
    registration_status: string
    balance_tokens: Tokens
    earnings_tokens: Tokens
    earnings_total_tokens: Tokens
  } | null
  services: { type: string; status: string }[]
  sessions: {
    count: number
    consumers: number
    bytes_received: number
    bytes_sent: number
    duration_seconds: number
    // a Decimal of core, serialized as a string (checked against core's JSON)
    tokens_myst: string
  }
  problems: string[]
}

const BYTES_PER_UNIT = 1024
const BYTE_UNITS = ['B', 'KiB', 'MiB', 'GiB', 'TiB'] as const
const WEI_DIGITS = 18
const MYST_SHOWN_DIGITS = 4

/** `1536` → `1.5 KiB`, whole bytes as they are; the same as `human_bytes` of the CLI. */
export const humanBytes = (count: number): string => {
  let value = count
  for (const unit of BYTE_UNITS) {
    if (value < BYTES_PER_UNIT || unit === 'TiB') {
      return unit === 'B' ? `${count} B` : `${value.toFixed(1)} ${unit}`
    }
    value /= BYTES_PER_UNIT
  }
  return `${count} B`
}

/** A Go duration without its fraction of a second (`72h3m5.123s` → `72h3m5s`, `192ms` → `<1s`), like the CLI. */
export const shortUptime = (uptime: string): string => {
  if (/^\d+(\.\d+)?(ms|µs|us|ns)$/.test(uptime)) {
    return '<1s'
  }
  return uptime.replace(/(\d+)\.\d+s$/, '$1s')
}

/** MYST from the exact wei string, without floating point: up to four decimals, trailing zeros dropped. */
export const formatMyst = (wei: string): string => {
  if (!/^\d+$/.test(wei)) {
    return '0'
  }
  const digits = wei.padStart(WEI_DIGITS + 1, '0')
  const whole = digits.slice(0, -WEI_DIGITS).replace(/^0+(?=\d)/, '')
  const fraction = digits.slice(-WEI_DIGITS, -WEI_DIGITS + MYST_SHOWN_DIGITS).replace(/0+$/, '')
  return fraction ? `${whole}.${fraction}` : whole
}
