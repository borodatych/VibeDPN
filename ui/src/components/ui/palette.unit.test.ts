import { DEFAULT_PALETTE, normalizePalette } from '@/components/ui/palette'
import { describe, expect, test } from 'bun:test'

describe('palette of the panel', () => {
  test('terracotta by default, as in VibeSter', () => {
    expect(DEFAULT_PALETTE).toBe('terracotta')
    expect(normalizePalette(undefined)).toBe('terracotta')
  })

  test('a stale or foreign cookie falls back to the default, a known one is kept', () => {
    expect(normalizePalette('neon')).toBe('terracotta')
    expect(normalizePalette('stock')).toBe('stock')
    expect(normalizePalette('midnight')).toBe('midnight')
  })
})
