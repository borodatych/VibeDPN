import type { z } from 'zod'

/**
 * Drop entries from an object whose value equals the Zod schema's default for that key, plus any `undefined` entries.
 *
 * Useful for collapsing form/query objects before serializing them into a URL so the visible querystring only carries
 * deviations from the schema defaults.
 *
 * Comparison is done by `String(value) === String(default)`, so it works for primitives only.
 *
 * @tags util, zod, query
 */
export const deleteDefaultsAndUndefined = <T extends Record<string, unknown>>(
  source: T,
  schema: z.ZodObject<any>,
): T => {
  return Object.fromEntries(
    Object.entries(source)
      .map(([key, value]) => {
        if (
          typeof value !== 'number' &&
          typeof value !== 'string' &&
          typeof value !== 'boolean' &&
          typeof value !== 'undefined'
        ) {
          return [key, value]
        }
        const valueNormalized = String(value)
        const defaultValue = schema.shape?.[key]?.def?.defaultValue
        const defaultValueNormalized = String(defaultValue)
        if (valueNormalized === defaultValueNormalized) {
          return [key, undefined]
        }
        return [key, value]
      })
      .filter(([_, value]) => value !== undefined),
  ) as T
}
