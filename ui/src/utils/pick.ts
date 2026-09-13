import type { Prettify } from '@/types'
import { isPlainObject } from '@/utils'

export const pick = <TValue, TKey extends keyof TValue>(value: TValue, keys: readonly TKey[]): Pick<TValue, TKey> => {
  const result: Record<PropertyKey, unknown> = {}
  if (!isPlainObject(value)) {
    return result as Pick<TValue, TKey>
  }
  for (const key of keys) {
    if (key in value) {
      result[key] = value[key as string]
    }
  }
  return result as Pick<TValue, TKey>
}
export const pickPretty = <TValue, TKey extends keyof TValue>(
  value: TValue,
  keys: readonly TKey[],
): Prettify<Pick<TValue, TKey>> => {
  return pick(value, keys)
}

export const omit = <TValue, TKey extends keyof TValue>(value: TValue, keys: readonly TKey[]): Omit<TValue, TKey> => {
  const result: Record<PropertyKey, unknown> = {}
  if (!isPlainObject(value)) {
    return result as Omit<TValue, TKey>
  }
  const omittedKeys = new Set<keyof TValue>(keys)
  for (const [key, entryValue] of Object.entries(value)) {
    if (!omittedKeys.has(key as keyof TValue)) {
      result[key] = entryValue
    }
  }
  return result as Omit<TValue, TKey>
}
export const omitPretty = <TValue, TKey extends keyof TValue>(
  value: TValue,
  keys: readonly TKey[],
): Prettify<Omit<TValue, TKey>> => {
  return omit(value, keys)
}

export const split = <TValue, TKey extends keyof TValue>(
  value: TValue,
  keys: readonly TKey[],
): [Pick<TValue, TKey>, Omit<TValue, TKey>] => {
  return [pick(value, keys), omit(value, keys)]
}
export const splitPretty = <TValue, TKey extends keyof TValue>(
  value: TValue,
  keys: readonly TKey[],
): [Prettify<Pick<TValue, TKey>>, Prettify<Omit<TValue, TKey>>] => {
  return [pickPretty(value, keys), omitPretty(value, keys)]
}
