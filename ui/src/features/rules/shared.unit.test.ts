import {
  cdnCandidates,
  channelLabel,
  channelText,
  listCopyText,
  ruleOf,
  wgExitNames,
  withCdn,
  type DomainRule,
  type JournalEntry,
} from '@/features/rules/shared'
import { baseT } from '@/modules/i18n/translator'
import { describe, expect, test } from 'bun:test'

const kinopoisk: DomainRule = {
  domain: 'kinopoisk.ru',
  via: 'direct',
  country: null,
  uplink: null,
  learn: true,
  also: ['kp-cdn.net'],
}
const zdf: DomainRule = { domain: 'zdf.de', via: 'dpn', country: 'DE', uplink: null, learn: false, also: [] }
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
    expect(channelLabel('smart_vps', baseT)).toBe('VPS')
    expect(channelLabel('smart_dpn_de', baseT)).toBe('Mysterium DE')
    expect(channelLabel('smart_dpn_any', baseT)).toBe('Mysterium')
    expect(channelLabel('direct', baseT)).toBe('direct')
  })

  test('the copy of a list reads as core has it', () => {
    const list = {
      url: 'https://l.example/a.txt',
      via: 'vps' as const,
      country: null,
      uplink: null,
      domains: 0,
      fetched_at: null,
      error: '',
    }
    expect(listCopyText(list, baseT)).toBe('fetching…')
    expect(listCopyText({ ...list, error: 'HTTP 503' }, baseT)).toBe('no copy yet')
    expect(listCopyText({ ...list, domains: 12, fetched_at: 1_700_000_000 }, baseT)).toBe('12 domains')
  })

  test('a WireGuard exit is named by its channel, its set and the uplink keys of the status', () => {
    expect(wgExitNames([{ name: 'vps' }, { name: 'wg-proton' }, { name: 'dpn-de' }, { name: 'wg-my-vps' }])).toEqual([
      'my-vps',
      'proton',
    ])
    expect(channelText({ via: 'wg', country: null, uplink: 'proton' }, baseT)).toBe('WireGuard proton')
    expect(channelText({ via: 'dpn', country: 'DE', uplink: null }, baseT)).toBe('Mysterium DE')
    // core spells '-' as '_' in the set name; the label gives the name back as the owner wrote it
    expect(channelLabel('smart_wg_my_vps', baseT)).toBe('WireGuard my-vps')
  })
})
