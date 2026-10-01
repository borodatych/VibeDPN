import { PEER_NAME, peerFileName, peerLinkState, trafficSince, type Peer } from '@/features/peers/shared'
import { pagesOfRole } from '@/features/box/shared'
import { describe, expect, test } from 'bun:test'

const NOW = 1_790_000_000

const peer = (overrides: Partial<Peer> = {}): Peer => ({
  name: 'dacha',
  address: '10.78.0.2',
  public_key: 'k',
  created: '2026-09-30T10:00:00Z',
  endpoint: null,
  latest_handshake: NOW - 30,
  rx_bytes: 0,
  tx_bytes: 0,
  applied: true,
  tunnel_only: false,
  ...overrides,
})

describe('peers', () => {
  test('a peer is on the link while its handshake is fresh, silent after', () => {
    expect(peerLinkState(peer(), NOW)).toBe('online')
    expect(peerLinkState(peer({ latest_handshake: NOW - 181 }), NOW)).toBe('offline')
    expect(peerLinkState(peer({ latest_handshake: 0 }), NOW)).toBe('never')
    expect(peerLinkState(peer({ applied: false }), NOW)).toBe('pending')
    // as core lists a peer wg-server has not applied: no live fields at all
    expect(peerLinkState(peer({ applied: false, latest_handshake: null }), NOW)).toBe('pending')
    expect(peerLinkState(peer({ applied: null, latest_handshake: null }), NOW)).toBe('unknown')
  })

  test('names are the ones core takes, and the file is a .conf', () => {
    expect(PEER_NAME.test('dacha-2')).toBe(true)
    expect(PEER_NAME.test('Dacha')).toBe(false)
    expect(PEER_NAME.test('-dacha')).toBe(false)
    expect(PEER_NAME.test('a'.repeat(33))).toBe(false)
    expect(peerFileName('dacha')).toBe('dacha.conf')
  })

  test('the totals cover the last 30 days, today included', () => {
    expect(trafficSince(new Date('2026-09-30T12:00:00Z'))).toBe('2026-09-01')
  })
})

describe('pages of a role', () => {
  test('a VPS has peers and no LAN pages; a home box the other way round', () => {
    expect(pagesOfRole('vps')).toEqual(['home', 'peers', 'node', 'access', 'notifications', 'backup'])
    expect(pagesOfRole('home')).toContain('backup') // every role keeps a copy of itself
    expect(pagesOfRole('home')).not.toContain('peers')
    expect(pagesOfRole('home')).toContain('rules')
    expect(pagesOfRole(undefined)).toEqual(pagesOfRole('home'))
  })
})
