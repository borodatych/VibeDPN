import { readFileSync } from 'node:fs'
import path from 'node:path'

/** `ui/src`: the graph the import gates walk */
export const SRC = path.resolve(import.meta.dir, '..', '..')

// .ts is read as TypeScript and .tsx as JSX: in a .tsx file `<T>(x) =>` would parse as a tag
const transpilers = { ts: new Bun.Transpiler({ loader: 'ts' }), tsx: new Bun.Transpiler({ loader: 'tsx' }) }

/**
 * The specifiers `from` imports while it loads
 *
 * Imports of types only are erased and not listed
 *
 * A dynamic `import()` runs later, from a function, and is not listed either
 *
 * @tags test
 * @related importsOf
 */
export const specifiersOf = (from: string): string[] =>
  transpilers[from.endsWith('.tsx') ? 'tsx' : 'ts']
    .scanImports(readFileSync(from, 'utf8'))
    .filter(({ kind }) => kind !== 'dynamic-import')
    .map(({ path: specifier }) => specifier)

/**
 * The modules of `src/` that `from` evaluates while it loads
 *
 * @tags test
 * @related specifiersOf
 */
export const importsOf = (from: string): string[] =>
  specifiersOf(from).flatMap((specifier) => {
    try {
      const resolved = Bun.resolveSync(specifier, path.dirname(from))
      return resolved.startsWith(SRC) ? [resolved] : []
    } catch {
      return [] // a package or a generated file: outside the graph of src/
    }
  })

/**
 * Every module of `src/` that `from` evaluates, `from` included
 *
 * @tags test
 * @related importsOf
 */
export const closureOf = (from: string): Set<string> => {
  const seen = new Set([from])
  const walk = (file: string) => {
    for (const next of importsOf(file)) {
      if (!seen.has(next)) {
        seen.add(next)
        walk(next)
      }
    }
  }
  walk(from)
  return seen
}
