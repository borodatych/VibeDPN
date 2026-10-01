import {
  ADD_EXIT,
  bridgeLines,
  bridgeLinesProblem,
  exitEntries,
  MAX_TOR_BRIDGES,
  pickExit,
  missingWgParts,
  suggestExitName,
  WG_EXIT_NAME,
  xrayLinkProblem,
} from '@/features/uplinks/shared'
import { describe, expect, test } from 'bun:test'

const PROVIDER_FILE =
  '[Interface]\nPrivateKey = a\nAddress = 10.2.0.2/32\n\n[Peer]\nPublicKey = b\nEndpoint = 1.2.3.4:51820\n'

describe('WireGuard exits', () => {
  test('a downloaded file name becomes a usable exit name', () => {
    expect(suggestExitName('Proton NL#12.conf')).toBe('proton-nl-12')
    expect(suggestExitName('wg-US-FREE-3.conf')).toBe('wg-us-free-3')
    // too long, or nothing usable left: cut to 24, or the default the owner changes
    expect(suggestExitName('a-very-long-name-of-a-provider-file.conf')).toBe('a-very-long-name-of-a-pr')
    expect(suggestExitName('###.conf')).toBe('proton')
    for (const name of ['proton-nl-12', 'a-very-long-name-of-a-pr', 'proton']) {
      expect(WG_EXIT_NAME.test(name)).toBe(true)
    }
  })

  test('a text that is not a client file says what it lacks', () => {
    expect(missingWgParts(PROVIDER_FILE)).toEqual([])
    expect(missingWgParts('hello')).toEqual(['[Interface]', 'PrivateKey', '[Peer]', 'PublicKey'])
    expect(missingWgParts('[Interface]\nPrivateKey = a\n')).toEqual(['[Peer]', 'PublicKey'])
  })
})

describe('xrayLinkProblem', () => {
  test('tells apart nothing typed, a wrong scheme and something core can parse', () => {
    expect(xrayLinkProblem('')).toBe('empty')
    expect(xrayLinkProblem('   ')).toBe('empty')
    expect(xrayLinkProblem('https://example.org')).toBe('scheme')
    // the panel only checks the shape: what the link carries is core's business, and it answers
    // with the reason the owner reads
    expect(xrayLinkProblem('vless://user@host.example:443?security=reality')).toBeNull()
    expect(xrayLinkProblem('  vless://user@host.example:443  ')).toBeNull()
  })
})

describe('the exit shown on «Exits»', () => {
  const entries = exitEntries({ enabled: false }, { enabled: true }, [
    { name: 'proton', enabled: true, has_file: true },
  ])

  test('the list goes Tor, the masking exit, then the WireGuard exits', () => {
    expect(entries.map((entry) => entry.key)).toEqual(['tor', 'xray', 'wg-proton'])
  })

  test('the one in the URL when the box has it, else the first one on', () => {
    expect(pickExit(entries, 'wg-proton')).toBe('wg-proton')
    expect(pickExit(entries, ADD_EXIT)).toBe(ADD_EXIT)
    expect(pickExit(entries, 'wg-removed')).toBe('xray') // removed while open: not an empty page
    expect(pickExit(entries, undefined)).toBe('xray')
    expect(pickExit([], undefined)).toBe(ADD_EXIT)
  })
})

describe('Tor bridges', () => {
  test('keep the lines as core does: blank lines out, a torrc keyword dropped in any case', () => {
    expect(bridgeLines('  Bridge obfs4 203.0.113.9:443 ABCD cert=x\n\n bridge snowflake 192.0.2.3:80 \n')).toEqual([
      'obfs4 203.0.113.9:443 ABCD cert=x',
      'snowflake 192.0.2.3:80',
    ])
  })

  test('name the first line the gateway cannot run, counted among the non-blank ones', () => {
    expect(bridgeLinesProblem('\n  \n')).toEqual({ kind: 'empty' })
    expect(bridgeLinesProblem('obfs4 203.0.113.9:443\n\nwebtunnel 203.0.113.9:443 url=x')).toEqual({
      kind: 'webtunnel',
      line: 2,
    })
    expect(bridgeLinesProblem('snowflake\nobfs4 203.0.113.9:443')).toEqual({ kind: 'line', line: 1 })
    expect(bridgeLinesProblem('vless://u@host 1')).toEqual({ kind: 'line', line: 1 })
    expect(bridgeLinesProblem('meek_lite 192.0.2.20:80 url=x\nBridge obfs4 203.0.113.9:443')).toBeNull()
    expect(bridgeLinesProblem('obfs4 203.0.113.9:443\n'.repeat(MAX_TOR_BRIDGES + 1))).toEqual({ kind: 'tooMany' })
  })
})
