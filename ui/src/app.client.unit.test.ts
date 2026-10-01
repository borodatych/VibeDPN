import { closureOf, specifiersOf, SRC } from '@/test/lib/imports'
import { describe, expect, it } from 'bun:test'
import { readFileSync } from 'node:fs'
import path from 'node:path'

const APP = path.join(SRC, 'app.client.tsx')
const COLD_MARKER = '@point0/core/cold'
// a call, typed or not: `createContext(…)` or `createContext<State>(…)`
const CREATES_CONTEXT = /\bcreateContext\s*[<(]/

/** The modules Point0 keeps out of its hot store: every file importing the marker and all it imports. */
const coldModules = (): Set<string> => {
  const cold = new Set<string>()
  for (const file of new Bun.Glob('**/*.{ts,tsx}').scanSync({ cwd: SRC, absolute: true })) {
    // the text first: scanning every file of src/ would trip on the scripts with a shebang
    if (readFileSync(file, 'utf8').includes(COLD_MARKER) && specifiersOf(file).includes(COLD_MARKER)) {
      closureOf(file).forEach((item) => cold.add(item))
    }
  }
  return cold
}

/** The modules in the graph of `App` that create a React context. */
const contextModules = (): string[] =>
  [...closureOf(APP)].filter((file) => CREATES_CONTEXT.test(readFileSync(file, 'utf8')))

describe('app.client', () => {
  // `point0 dev --hot` copies the modules of points into a store, and App keeps importing the originals: a context
  // module in both graphs exists twice, App provides one context and the pages read the other's default.
  // A cold module is not copied, so App and the pages share one context.
  it('takes every React context of its graph from a cold module', () => {
    const cold = coldModules()
    expect(
      contextModules()
        .filter((file) => !cold.has(file))
        .map((file) => path.relative(SRC, file)),
    ).toEqual([])
  })
})
