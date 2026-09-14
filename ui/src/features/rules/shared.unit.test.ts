import {
  cdnCandidates,
  channelLabel,
  ruleOf,
  withCdn,
  type DomainRule,
  type JournalEntry,
} from '@/features/rules/shared'
import { describe, expect, test } from 'bun:test'

const kinopoisk: DomainRule = {
  domain: 'kinopoisk.ru',
  via: 'direct',
  country: null,
  learn: true,
  also: ['kp-cdn.net'],
}
const zdf: DomainRule = { domain: 'zdf.de', via: 'dpn', country: 'DE', learn: false, also: [] }
const rules = [kinopoisk, zdf]

const entry = (time: number, name: string, channel = 'direct'): JournalEntry => ({
  time,
  name,
  qtype: 'A',
  cached: false,
  addresses: ['198.18.0.10'],
  channel,
  learned_from: null,
})

describe('rules', () => {
  test('a rule covers its subdomains and its pinned CDNs', () => {
    expect(ruleOf('www.kinopoisk.ru.', rules)).toBe(kinopoisk)
    expect(ruleOf('img.kp-cdn.net', rules)).toBe(kinopoisk)
    expect(ruleOf('zdf.de', rules)).toBe(zdf)
    expect(ruleOf('ru', rules)).toBeNull()
    expect(ruleOf('notkinopoisk.ru', rules)).toBeNull()
  })

  test('a direct name right after a site is its CDN candidate, a late one is not', () => {
    const candidates = cdnCandidates(
      [
        entry(100, 'www.zdf.de', 'smart_dpn_de'),
        entry(104, 'video.akamaized.net'),
        entry(130, 'late.example.com'),
        entry(131, 'kinopoisk.ru', 'smart_direct'),
        entry(135, 'strm.yandex.net'),
        entry(136, 'img.kp-cdn.net', 'smart_direct'),
      ],
      rules,
    )
    expect(candidates.map((item) => [item.name, item.rule.domain])).toEqual([
      ['strm.yandex.net', 'kinopoisk.ru'],
      ['video.akamaized.net', 'zdf.de'],
    ])
  })

  test('the newest site wins and a name is offered once', () => {
    const candidates = cdnCandidates(
      [entry(1, 'zdf.de', 'smart_dpn_de'), entry(2, 'cdn.example'), entry(3, 'kinopoisk.ru'), entry(4, 'cdn.example')],
      rules,
    )
    expect(candidates).toHaveLength(1)
    expect(candidates[0]?.rule.domain).toBe('kinopoisk.ru')
  })

  test('a CDN is pinned once', () => {
    expect(withCdn(zdf, 'Video.Akamaized.net.').also).toEqual(['video.akamaized.net'])
    expect(withCdn(kinopoisk, 'kp-cdn.net')).toBe(kinopoisk)
  })

  test('channels read as the owner names them', () => {
    expect(channelLabel('smart_vps')).toBe('VPS')
    expect(channelLabel('smart_dpn_de')).toBe('Mysterium DE')
    expect(channelLabel('smart_dpn_any')).toBe('Mysterium')
    expect(channelLabel('direct')).toBe('direct')
  })
})
