import { passwordProblem } from '@/features/password/shared'
import { describe, expect, test } from 'bun:test'

describe('passwordProblem', () => {
  test('takes what core takes, typed twice the same, with the current one given', () => {
    expect(passwordProblem('old-panel-pass', 'new-panel-pass', 'new-panel-pass')).toBeNull()
    expect(passwordProblem('old', 'x'.repeat(72), 'x'.repeat(72))).toBeNull()
  })

  test('names the first reason it cannot be sent', () => {
    expect(passwordProblem('', 'new-panel-pass', 'new-panel-pass')).toBe('current')
    expect(passwordProblem('old', 'short', 'short')).toBe('length')
    // 37 Cyrillic letters are 74 bytes in UTF-8: past what bcrypt hashes
    expect(passwordProblem('old', 'я'.repeat(37), 'я'.repeat(37))).toBe('bytes')
    expect(passwordProblem('old', 'new-panel-pass', 'new-panel-pas')).toBe('mismatch')
  })
})
