import { formatMyst, humanBytes, shortUptime } from '@/features/node/shared'
import { describe, expect, test } from 'bun:test'

describe('node formatting', () => {
  test('bytes read like the CLI', () => {
    expect(humanBytes(512)).toBe('512 B')
    expect(humanBytes(1536)).toBe('1.5 KiB')
    expect(humanBytes(5 * 1024 ** 3)).toBe('5.0 GiB')
    expect(humanBytes(3 * 1024 ** 5)).toBe('3072.0 TiB')
  })

  test('uptime drops the fraction of a second', () => {
    expect(shortUptime('72h3m5.123456789s')).toBe('72h3m5s')
    expect(shortUptime('192.85ms')).toBe('<1s')
    expect(shortUptime('unknown')).toBe('unknown')
  })

  test('MYST comes from wei exactly', () => {
    expect(formatMyst('1500000000000000000')).toBe('1.5')
    expect(formatMyst('123456789000000000000')).toBe('123.4567')
    expect(formatMyst('20000000000000000')).toBe('0.02')
    expect(formatMyst('0')).toBe('0')
    expect(formatMyst('not-a-number')).toBe('0')
  })
})
