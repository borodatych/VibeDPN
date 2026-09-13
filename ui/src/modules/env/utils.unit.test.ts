import { createEnv } from '@/modules/env/utils'
import { afterEach, beforeEach, describe, expect, test } from 'bun:test'
import { z } from 'zod'

const shape = {
  TOKEN: z.string().min(1),
  PORT: z.coerce.number(),
  LEVEL: z.enum(['low', 'high']).default('low'),
  OPTIONAL: z.string().optional(),
}

const envKeys = Object.keys(shape)

const clearEnv = () => {
  for (const key of envKeys) {
    delete process.env[key]
  }
}

beforeEach(clearEnv)
afterEach(clearEnv)

const makeEnv = () => createEnv('app', shape)

describe('per-variable access', () => {
  test('parses and types a single variable', () => {
    process.env.PORT = '3000'
    expect(makeEnv().PORT).toBe(3000)
  })

  test('applies defaults', () => {
    expect(makeEnv().LEVEL).toBe('low')
  })

  test('returns undefined for an unset optional', () => {
    expect(makeEnv().OPTIONAL).toBeUndefined()
  })

  test('reads one variable without validating its siblings', () => {
    process.env.TOKEN = 'secret'
    // PORT is unset → invalid, but it is never touched
    const env = makeEnv()
    expect(env.TOKEN).toBe('secret')
    expect(() => env.PORT).toThrow('Invalid "app.PORT" environment variable')
  })

  test('exposes the ZodError as the cause', () => {
    process.env.TOKEN = ''
    const env = makeEnv()
    const read = () => env.TOKEN
    let cause: unknown
    try {
      read()
    } catch (error) {
      cause = (error as Error).cause
    }
    expect(cause).toBeInstanceOf(z.ZodError)
  })

  test('caches the first read', () => {
    process.env.TOKEN = 'first'
    const env = makeEnv()
    expect(env.TOKEN).toBe('first')
    process.env.TOKEN = 'second'
    expect(env.TOKEN).toBe('first')
  })

  test('caches an undefined optional too', () => {
    const env = makeEnv()
    expect(env.OPTIONAL).toBeUndefined()
    process.env.OPTIONAL = 'now-set'
    expect(env.OPTIONAL).toBeUndefined()
  })
})

describe('value', () => {
  test('validates and returns the whole object', () => {
    process.env.TOKEN = 'secret'
    process.env.PORT = '8080'
    const { value } = makeEnv()
    expect(value.TOKEN).toBe('secret')
    expect(value.PORT).toBe(8080)
    expect(value.LEVEL).toBe('low')
  })

  test('throws a named error when any variable is invalid', () => {
    process.env.TOKEN = 'secret'
    // PORT is missing
    const env = makeEnv()
    expect(() => env.value).toThrow('Invalid "app" environment variables')
  })

  test('caches after the first successful read', () => {
    process.env.TOKEN = 'secret'
    process.env.PORT = '1'
    const env = makeEnv()
    expect(env.value.TOKEN).toBe('secret')
    process.env.TOKEN = 'changed'
    expect(env.value.TOKEN).toBe('secret')
  })
})

describe('getOrUndefined', () => {
  test('answers undefined for a variable that is not set', () => {
    expect(makeEnv().getOrUndefined('TOKEN')).toBeUndefined()
  })

  test('still throws when the variable IS set but invalid — absent is an answer, wrong never is', () => {
    process.env.TOKEN = ''
    expect(() => makeEnv().getOrUndefined('TOKEN')).toThrow('Invalid "app.TOKEN" environment variable')
  })

  test('applies the default instead of answering undefined', () => {
    expect(makeEnv().getOrUndefined('LEVEL')).toBe('low')
  })

  test('parses and caches like a plain read', () => {
    process.env.PORT = '3000'
    const env = makeEnv()
    expect(env.getOrUndefined('PORT')).toBe(3000)
    process.env.PORT = '4000'
    expect(env.getOrUndefined('PORT')).toBe(3000)
    expect(env.PORT).toBe(3000)
  })
})

describe('validate', () => {
  test('throws when anything is invalid', () => {
    expect(() => makeEnv().validate()).toThrow('Invalid "app" environment variables')
  })

  test('passes when valid and ignores later breakage', () => {
    process.env.TOKEN = 'secret'
    process.env.PORT = '1'
    const env = makeEnv()
    expect(() => env.validate()).not.toThrow()
    process.env.TOKEN = ''
    expect(() => env.validate()).not.toThrow()
    expect(env.TOKEN).toBe('secret')
  })
})

describe('metadata', () => {
  test('keys lists the variable names in shape order', () => {
    expect(makeEnv().keys).toEqual(['TOKEN', 'PORT', 'LEVEL', 'OPTIONAL'])
  })

  test('exposes the raw shape and the compiled schema', () => {
    const env = makeEnv()
    expect(env.shape).toBe(shape)
    expect(env.schema.safeParse({ TOKEN: 'x', PORT: 1 }).success).toBe(true)
  })

  test('only variables enumerate; metadata stays hidden', () => {
    expect(Object.keys(makeEnv()).sort()).toEqual(['LEVEL', 'OPTIONAL', 'PORT', 'TOKEN'])
  })

  test('supports destructuring', () => {
    process.env.TOKEN = 'secret'
    process.env.PORT = '5'
    const { TOKEN, PORT } = makeEnv()
    expect(TOKEN).toBe('secret')
    expect(PORT).toBe(5)
  })
})
