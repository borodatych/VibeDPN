import { z } from 'zod'

type EnvShape = Record<string, z.ZodType>

type EnvValues<TShape extends EnvShape> = {
  [K in keyof TShape]: z.infer<TShape[K]>
}

type Env<TShape extends EnvShape> = EnvValues<TShape> & {
  /** Validate every variable at once, throwing on the first invalid one. Cached after the first success. */
  validate: () => void
  /**
   * The value, or `undefined` when the variable is not set at all — for the few reads that legitimately happen where it
   * cannot be: module initialization that also runs during `point0 build`, which has no env at all (the Dockerfile
   * copies no `.env`, and the platform hands a build no service variables). A value that IS set still has to be valid,
   * so a typo fails here exactly as it would through `env.FOO`, and a variable with a default still gets its default.
   */
  getOrUndefined: <TKey extends keyof TShape & string>(key: TKey) => EnvValues<TShape>[TKey] | undefined
  /** The declared variable names, in shape order. */
  keys: Array<keyof TShape & string>
  /** All variables as one object — validated lazily on first read, then cached. */
  value: EnvValues<TShape>
  /** The raw per-variable shape passed in. */
  shape: TShape
  /** `z.object(shape)`, for callers that need the schema itself. */
  schema: z.ZodObject<TShape>
}

/**
 * Builds a lazily-validated env handle from a Zod shape. Reading `env.FOO` validates only `FOO` against
 * `process.env.FOO`; reading `env.value` validates the whole shape at once. Each variable (and the full object) is
 * validated once and then cached, so repeated reads are free.
 *
 * Per-key laziness is the point: client and server share one `process.env` but declare different shapes, so reading a
 * client variable must not trip over a missing server secret. Touch only what you read, or call `validate()` to fail
 * fast at startup.
 *
 * The names `validate`, `getOrUndefined`, `keys`, `value`, `shape`, and `schema` are reserved metadata — don't use them
 * as variable names (env names are `UPPER_SNAKE_CASE`, so this never collides in practice). Only the variables
 * enumerate; metadata is non-enumerable, so `Object.keys(env)` returns exactly the variable names.
 *
 * @tags env, zod
 * @related serverEnv, clientEnv, sharedEnv
 */
export const createEnv = <TShape extends EnvShape>(name: string, shape: TShape): Env<TShape> => {
  const schema = z.object(shape)
  const keys = Object.keys(shape) as Array<keyof TShape & string>
  const parsed: Partial<EnvValues<TShape>> = {}
  let validated = false

  const validateOne = (key: keyof TShape & string) => {
    if (key in parsed) {
      return
    }
    const result = shape[key].safeParse(process.env[key])
    if (!result.success) {
      throw new Error(`Invalid "${name}.${key}" environment variable`, { cause: result.error })
    }
    parsed[key] = result.data
  }

  const getOrUndefined = <TKey extends keyof TShape & string>(key: TKey): EnvValues<TShape>[TKey] | undefined => {
    if (key in parsed) {
      return parsed[key]
    }
    const raw = process.env[key]
    const result = shape[key].safeParse(raw)
    if (result.success) {
      parsed[key] = result.data
      return result.data
    }
    // Absent is an answer here; invalid never is.
    if (raw === undefined) {
      return undefined
    }
    throw new Error(`Invalid "${name}.${key}" environment variable`, { cause: result.error })
  }

  const validate = () => {
    if (validated) {
      return
    }
    const result = schema.safeParse(process.env)
    if (!result.success) {
      throw new Error(`Invalid "${name}" environment variables`, { cause: result.error })
    }
    Object.assign(parsed, result.data)
    validated = true
  }

  const env = {} as Env<TShape>
  Object.defineProperties(env, {
    validate: { value: validate },
    getOrUndefined: { value: getOrUndefined },
    keys: { value: keys },
    shape: { value: shape },
    schema: { value: schema },
    value: {
      get: () => {
        validate()
        return parsed as EnvValues<TShape>
      },
    },
  })
  for (const key of keys) {
    Object.defineProperty(env, key, {
      enumerable: true,
      get: () => {
        validateOne(key)
        return parsed[key]
      },
    })
  }

  return env
}
