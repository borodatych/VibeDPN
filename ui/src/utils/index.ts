import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/**
 * Express millisecond durations with the `ms` library — never a magic number like `86_400_000`. Clearer, and the
 * project default wherever a duration is needed (timeouts, TTLs, windows). `parse`/`format` cover the inverse.
 *
 * @example
 *   ms('1 day') // 86400000
 *   gte: new Date(Date.now() - ms('30m'))
 *
 * @id ms
 * @tags rule, util, ms
 */

/**
 * Memoize a function with the `memoizee` library instead of hand-rolling a cache. `memoize(fn, opts)` caches by args;
 * pass `promise: true` for async, `maxAge` (use `ms`) for a TTL, `max` to bound size. Reach for it for any
 * cached/derived result — don't add a competing cache dependency.
 *
 * @example
 *   const getConfig = memoize(loadConfig, { promise: true, maxAge: ms('5m') })
 *
 * @id memoizee
 * @tags rule, util, memoizee
 * @related ms
 */

export function cn(...inputs: ClassValue[]) {
  // the plugin inspects clsx() arguments as classnames and chokes on the bare identifier
  // eslint-disable-next-line tailwindcss/no-custom-classname
  return twMerge(clsx(inputs))
}

export const isPlainObject = (value: unknown): value is Record<string, unknown> => {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

export const isPromiseLike = <T>(value: T | PromiseLike<T>): value is PromiseLike<T> => {
  return (
    typeof value === 'object' && value !== null && typeof (value as { then?: unknown } | undefined)?.then === 'function'
  )
}

export const objectKeys = <T extends object>(object: T): (keyof T)[] => {
  return Object.keys(object) as (keyof T)[]
}
