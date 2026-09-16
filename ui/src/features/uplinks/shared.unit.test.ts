import { missingWgParts, suggestExitName, WG_EXIT_NAME } from '@/features/uplinks/shared'
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
