import { describe, expect, it } from 'bun:test'
import { readFileSync } from 'node:fs'
import path from 'node:path'

const SRC = path.resolve(import.meta.dir, '..')
const ROOT = path.join(SRC, 'lib', 'root.tsx')
// .ts is read as TypeScript and .tsx as JSX: in a .tsx file `<T>(x) =>` would parse as a tag
const transpilers = { ts: new Bun.Transpiler({ loader: 'ts' }), tsx: new Bun.Transpiler({ loader: 'tsx' }) }

/**
 * The modules of `src/` that `from` evaluates while it loads
 *
 * Imports of types only are erased and not listed
 *
 * A dynamic `import()` runs later, from a function, when `root` exists: it cannot read `root` too early
 */
const importsOf = (from: string): string[] =>
  transpilers[from.endsWith('.tsx') ? 'tsx' : 'ts']
    .scanImports(readFileSync(from, 'utf8'))
    .flatMap(({ path: specifier, kind }) => {
      if (kind === 'dynamic-import') {
        return []
      }
      try {
        const resolved = Bun.resolveSync(specifier, path.dirname(from))
        return resolved.startsWith(SRC) ? [resolved] : []
      } catch {
        return [] // a package or a generated file: outside the graph of src/
      }
    })

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
