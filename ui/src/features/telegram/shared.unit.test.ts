import { alertAfterValid, tokenProblem } from '@/features/telegram/shared'
import { describe, expect, test } from 'bun:test'

describe('telegram', () => {
  test('a token is the number of the bot, a colon and the secret', () => {
    expect(tokenProblem(' 123456:AAH-s3cr3t_token \n')).toBeNull()
    expect(tokenProblem('   ')).toBe('empty')
    expect(tokenProblem('123456')).toBe('format')
    expect(tokenProblem('bot:secret')).toBe('format')
    expect(tokenProblem('123:a b')).toBe('format')
  })

  test('a threshold of silence is whole seconds between 15 s and a day', () => {
    expect(alertAfterValid(60)).toBe(true)
    expect(alertAfterValid(15)).toBe(true)
    expect(alertAfterValid(86400)).toBe(true)
    expect(alertAfterValid(14)).toBe(false)
    expect(alertAfterValid(90.5)).toBe(false)
    expect(alertAfterValid(86401)).toBe(false)
  })
})
