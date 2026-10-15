import { navOfRole, pagesOfRole } from '@/features/box/shared'
import {
  barPercent,
  bytesToBase64,
  countByFilter,
  dotted,
  formatEta,
  formatPercent,
  formatRate,
  formatRatio,
  magnetProblem,
  matchesFilter,
  speedLimitProblem,
  statusKey,
  subdirProblem,
  torrentFileProblem,
  usedFraction,
  type TorrentSummary,
} from '@/features/torrents/shared'
import { baseStrings } from '@/modules/i18n/base'
import { translate } from '@/modules/i18n/shared'
import { describe, expect, test } from 'bun:test'

const t = ((key: string, params?: Record<string, string | number>) =>
  translate(baseStrings, key, params)) as Parameters<typeof formatEta>[1]

const torrent = (patch: Partial<TorrentSummary>): TorrentSummary => ({
  id: '7ad0393e3790590660678ef4e876a5248dcdad8d',
  name: 'ubuntu.iso',
  status: 'downloading',
  progress: 0.5,
  rate_down: 0,
  rate_up: 0,
  eta: null,
  size: 1000,
  ratio: null,
  error: null,
  ...patch,
})

describe('numbers of the list', () => {
  test('a rate is bytes per second in the units of the panel, and nothing flowing is a dash', () => {
    expect(formatRate(1048576)).toBe('1.0 MiB/s')
    expect(formatRate(2048)).toBe('2.0 KiB/s')
    expect(formatRate(0)).toBe('—')
  })

  test('the time left keeps its two largest units, and an unknown one is a dash', () => {
    expect(formatEta(null, t)).toBe('—')
    expect(formatEta(-1, t)).toBe('—')
    expect(formatEta(42, t)).toBe('42 s')
    expect(formatEta(600, t)).toBe('10 min')
    expect(formatEta(3600 * 3 + 60 * 20 + 5, t)).toBe('3 h 20 min')
    expect(formatEta(86400 * 2 + 3600 * 5, t)).toBe('2 d 5 h')
  })

  test('progress is a percent with one digit, and a bar never leaves its track', () => {
    expect(formatPercent(0.4237)).toBe('42.4%')
    expect(formatPercent(1.7)).toBe('100.0%')
    expect(formatPercent(Number.NaN)).toBe('0.0%')
    expect(barPercent(-1)).toBe(0)
    expect(barPercent(0.426)).toBe(43)
  })

  test('a ratio has two digits, unknown is a dash', () => {
    expect(formatRatio(0.1)).toBe('0.10')
    expect(formatRatio(null)).toBe('—')
  })

  test('small print is set apart by a middle dot', () => {
    expect(dotted('ext4', '1.0 TiB', '/dev/sda1')).toBe('ext4 · 1.0 TiB · /dev/sda1')
  })

  test('the disk is as full as the free space says, and unknown until Transmission answers', () => {
    expect(usedFraction({ free_bytes: 25, total_bytes: 100 })).toBe(0.75)
    expect(usedFraction({ free_bytes: null, total_bytes: 100 })).toBeNull()
    expect(usedFraction({ free_bytes: 0, total_bytes: 0 })).toBeNull()
  })
})

describe('filters of the list', () => {
  const list = [
    torrent({ id: 'a', status: 'downloading' }),
    torrent({ id: 'b', status: 'download_wait' }),
    torrent({ id: 'c', status: 'seeding', progress: 1 }),
    torrent({ id: 'd', status: 'stopped' }),
    torrent({ id: 'e', status: 'downloading', error: 'Tracker gave an error' }),
  ]

  test('each torrent is in the filter of its status, and a stalled one also in «error»', () => {
    const ids = (filter: Parameters<typeof matchesFilter>[1]) =>
      list.filter((item) => matchesFilter(item, filter)).map((item) => item.id)
    expect(ids('all')).toEqual(['a', 'b', 'c', 'd', 'e'])
    expect(ids('downloading')).toEqual(['a', 'b', 'e'])
    expect(ids('seeding')).toEqual(['c'])
    expect(ids('paused')).toEqual(['d'])
    expect(ids('error')).toEqual(['e'])
  })

  test('the buttons count what is behind them', () => {
    expect(countByFilter(list)).toEqual({ all: 5, downloading: 3, seeding: 1, paused: 1, error: 1 })
    expect(countByFilter([])).toEqual({ all: 0, downloading: 0, seeding: 0, paused: 0, error: 0 })
  })

  test('trouble names the torrent, whatever it was doing', () => {
    expect(statusKey(torrent({ status: 'seeding' }))).toBe('torrents.status.seeding')
    expect(statusKey(torrent({ status: 'seeding', error: 'Disk full' }))).toBe('torrents.status.error')
  })
})

describe('what is added', () => {
  test('a magnet link says why it is not one yet', () => {
    expect(magnetProblem('magnet:?xt=urn:btih:7ad0393e3790590660678ef4e876a5248dcdad8d&dn=x')).toBeNull()
    expect(magnetProblem('  ')).toBe('empty')
    expect(magnetProblem('https://example.org/a.torrent')).toBe('format')
    expect(magnetProblem(`magnet:?xt=urn:btih:${'a'.repeat(9000)}`)).toBe('long')
  })

  test('a subfolder is one name inside the downloads, and empty is the downloads themselves', () => {
    expect(subdirProblem('')).toBeNull()
    expect(subdirProblem('films')).toBeNull()
    expect(subdirProblem('films/2026')).toBe('format')
    expect(subdirProblem('..')).toBe('format')
    expect(subdirProblem('a\\b')).toBe('format')
  })

  test('a file must be a torrent of a sane size', () => {
    expect(torrentFileProblem({ name: 'a.torrent', size: 4000 })).toBeNull()
    expect(torrentFileProblem({ name: 'A.TORRENT', size: 4000 })).toBeNull()
    expect(torrentFileProblem({ name: 'a.zip', size: 4000 })).toBe('extension')
    expect(torrentFileProblem({ name: 'a.torrent', size: 0 })).toBe('empty')
    expect(torrentFileProblem({ name: 'a.torrent', size: 50 * 1024 * 1024 })).toBe('large')
  })

  test('a large file becomes base64 without overflowing the stack', () => {
    expect(bytesToBase64(new Uint8Array([104, 105]))).toBe('aGk=')
    const big = new Uint8Array(300_000).fill(65)
    expect(atob(bytesToBase64(big))).toBe('A'.repeat(300_000))
  })

  test('a speed limit is a whole number of kB/s', () => {
    expect(speedLimitProblem('500')).toBeNull()
    expect(speedLimitProblem('0')).toBeNull()
    expect(speedLimitProblem('')).toBe('format')
    expect(speedLimitProblem('5.5')).toBe('format')
    expect(speedLimitProblem('-1')).toBe('format')
    expect(speedLimitProblem('99999999')).toBe('format')
  })
})

describe('the menu', () => {
  test('the torrents page is for the roles with a LAN, and only while the client is on', () => {
    expect(pagesOfRole('home')).not.toContain('torrents')
    expect(pagesOfRole('home', true)).toContain('torrents')
    expect(pagesOfRole('client', true)).toContain('torrents')
    expect(pagesOfRole('vps', true)).not.toContain('torrents')
  })

  test('it sits in the menu «More», and every page is in exactly one of the two lists', () => {
    expect(navOfRole('home', true).more).toContain('torrents')
    expect(navOfRole('home', true).main).not.toContain('torrents')
    const { main, more } = navOfRole('home', true)
    expect([...main, ...more].sort()).toEqual([...pagesOfRole('home', true)].sort())
  })
})
