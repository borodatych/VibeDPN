import { describe, expect, test } from 'bun:test'
import { ESLint, Linter } from 'eslint'
import react from 'eslint-plugin-react'
import { join, relative } from 'node:path'
import tseslint from 'typescript-eslint'

const UI = join(import.meta.dir, '../../..')
const SRC = join(UI, 'src')
const GATE_RULES = ['react/jsx-no-literals', 'no-restricted-syntax'] as const

const eslint = new ESLint({ cwd: UI })
const markupFiles = [...new Bun.Glob('**/*.tsx').scanSync(SRC)]
  .filter((file) => !file.includes('.test.'))
  .map((file) => join(SRC, file))

/** The two rules of the gate exactly as eslint.config.js gives them to a file of the panel. */
const gateRulesOf = async (file: string): Promise<Partial<Linter.RulesRecord>> => {
  const { rules } = (await eslint.calculateConfigForFile(file)) as { rules: Linter.RulesRecord }
  return Object.fromEntries(GATE_RULES.map((rule) => [rule, rules[rule]]))
}

/** A rule entry is either a bare severity or a tuple that starts with it. */
const severityOf = (entry: Linter.RuleEntry | undefined): Linter.RuleEntry | undefined =>
  Array.isArray(entry) ? entry[0] : entry

/** The messages of the gate on a snippet of markup: syntax only, no type information. */
const gateMessages = async (code: string): Promise<string[]> => {
  const linter = new Linter({ configType: 'flat' })
  const config: Linter.Config = {
    files: ['**/*.tsx'],
    languageOptions: { parser: tseslint.parser, parserOptions: { ecmaFeatures: { jsx: true } } },
    plugins: { react },
    rules: await gateRulesOf(join(SRC, 'components/ui/button.tsx')),
  }
  return linter.verify(code, config, 'probe.tsx').map(({ line, ruleId }) => `${line} ${ruleId}`)
}

describe('i18n gate of the markup', () => {
  // The words of a primitive show up on every screen that uses it: a gate over a list of screens misses them
  test('covers every file with markup, primitives included', async () => {
    const uncovered: string[] = []
    for (const file of markupFiles) {
      const rules = await gateRulesOf(file)
      if (GATE_RULES.some((rule) => severityOf(rules[rule]) !== 2)) {
        uncovered.push(relative(SRC, file))
      }
    }
    expect(markupFiles.length).toBeGreaterThan(0)
    expect(uncovered).toEqual([])
  })

  test('catches words in text, text props and the branches of an expression', async () => {
    const code = [
      'export const Probe = ({ on }: { on: boolean }) => (',
      '  <div className={on ? "flex" : "hidden"}>',
      '    <span>Yes</span>',
      '    <span title="Hint text" />',
      '    <span aria-label={"Close it"} />',
      '    {on ? "Enabled" : null}',
      '    {on && "Shown"}',
      '  </div>',
      ')',
    ].join('\n')
    expect(await gateMessages(code)).toEqual([
      '3 react/jsx-no-literals',
      '4 no-restricted-syntax',
      '5 no-restricted-syntax',
      '6 no-restricted-syntax',
      '7 no-restricted-syntax',
    ])
  })

  test('lets through what is the same in every language: numbers, signs, class names', async () => {
    const code = [
      'export const Probe = ({ on }: { on: boolean }) => (',
      '  <div title="404" className={on ? "flex" : "hidden"}>',
      '    <span>/</span>',
      '  </div>',
      ')',
    ].join('\n')
    expect(await gateMessages(code)).toEqual([])
  })
})
