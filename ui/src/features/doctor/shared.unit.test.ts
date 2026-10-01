import { countVerdicts, problemsFirst, type Check } from '@/features/doctor/shared'
import { describe, expect, test } from 'bun:test'

const check = (name: string, verdict: Check['verdict']): Check => ({ name, verdict, detail: '', hint: '' })

describe('doctor report', () => {
  const checks = [check('config', 'ok'), check('exit dpn', 'warn'), check('router', 'fail'), check('docker', 'ok')]

  test('failures first, then warnings, each kept in the order of doctor', () => {
    expect(problemsFirst(checks).map((item) => item.name)).toEqual(['router', 'exit dpn', 'config', 'docker'])
    expect(checks[0]?.name).toBe('config') // the report itself is not reordered
  })

  test('counts every verdict', () => {
    expect(countVerdicts(checks)).toEqual({ ok: 2, warn: 1, fail: 1 })
    expect(countVerdicts([])).toEqual({ ok: 0, warn: 0, fail: 0 })
  })
})
