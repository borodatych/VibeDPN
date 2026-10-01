import { importsOf, SRC } from '@/test/lib/imports'
import { describe, expect, it } from 'bun:test'
import path from 'node:path'

const ROOT = path.join(SRC, 'lib', 'root.tsx')

/** Every chain of imports from `lib/root` that comes back to it. */
const cyclesBackToRoot = (): string[][] => {
  const cycles: string[][] = []
  const seen = new Set<string>()
  const walk = (file: string, chain: string[]) => {
    for (const next of importsOf(file)) {
      if (next === ROOT) {
        cycles.push([...chain, next].map((item) => path.relative(SRC, item)))
      } else if (!seen.has(next)) {
        seen.add(next)
        walk(next, [...chain, next])
      }
    }
  }
  walk(ROOT, [ROOT])
  return cycles
}

describe('lib/root', () => {
  // A module in the graph of root that imports root reads it before it exists: `bun dev` loads modules one by one and
  // stops with "Cannot access 'root' before initialization"; the bundled build only hides it by its order.
  it('never imports, through any module, a module that imports it back', () => {
    expect(cyclesBackToRoot()).toEqual([])
  })
})
