/**
 * Type-preserving (de)serialization for option values used by `X*` select-like components.
 *
 * HTML form controls only carry strings. These helpers encode primitives as `"<type>:<value>"` (e.g. `"number:42"`,
 * `"date:2026-01-01T00:00:00.000Z"`, `"null:null"`) so the original type round-trips through the DOM. Strings without a
 * recognized prefix are passed through unchanged.
 *
 * Use `stringifyXOptionPrimitiveValue` when writing a value into a control and `parseXOptionPrimitiveValue` when
 * reading one back.
 *
 * @tags util, form, select
 */

export type XOptionValueType = 'number' | 'string' | 'boolean' | 'null' | 'date' | 'json'

export type XOptionJsonValue =
  string | number | boolean | null | readonly XOptionJsonValue[] | { readonly [key: string]: XOptionJsonValue }

export type XOptionValue = XOptionJsonValue | Date

export type XOptionValueLike = {
  value: XOptionValue
  valueType?: XOptionValueType
}

const xOptionValueTypes = ['number', 'string', 'boolean', 'null', 'date', 'json'] as const

const isXOptionValueType = (value: string): value is XOptionValueType =>
  xOptionValueTypes.includes(value as XOptionValueType)

const getXOptionValueType = (value: XOptionValue, valueType?: XOptionValueType): XOptionValueType => {
  if (valueType) {
    return valueType
  }
  if (value === null) {
    return 'null'
  }
  if (value instanceof Date) {
    return 'date'
  }
  if (typeof value === 'object') {
    return 'json'
  }
  if (typeof value === 'number') {
    return 'number'
  }
  if (typeof value === 'boolean') {
    return 'boolean'
  }
  return 'string'
}

const stringifyXOptionValue = (value: XOptionValue, valueType?: XOptionValueType) => {
  const type = getXOptionValueType(value, valueType)

  switch (type) {
    case 'boolean':
      return value === true || value === 'true' ? 'true' : 'false'
    case 'date':
      return (value instanceof Date ? value : new Date(String(value))).toISOString()
    case 'json':
      return JSON.stringify(value)
    case 'null':
      return 'null'
    case 'number':
      return String(Number(value))
    case 'string':
      return String(value)
  }
}

export const stringifyXOptionPrimitiveValue = (value: XOptionValue, valueType?: XOptionValueType) => {
  const type = getXOptionValueType(value, valueType)
  const stringValue = stringifyXOptionValue(value, type)

  if (type === 'string') {
    return stringValue
  }
  return `${type}:${stringValue}`
}

const parsePrefixedXOptionPrimitiveValue = (primitiveValue: string): XOptionValue => {
  const separatorIndex = primitiveValue.indexOf(':')

  if (separatorIndex === -1) {
    return primitiveValue
  }

  const type = primitiveValue.slice(0, separatorIndex)
  const value = primitiveValue.slice(separatorIndex + 1)

  if (!isXOptionValueType(type)) {
    return primitiveValue
  }

  switch (type) {
    case 'boolean':
      return value === 'true'
    case 'date':
      return new Date(value)
    case 'json':
      return JSON.parse(value) as XOptionJsonValue
    case 'null':
      return null
    case 'number':
      return Number(value)
    case 'string':
      return value
  }
}

export const parseXOptionPrimitiveValue = (
  primitiveValue: string,
  options?: readonly XOptionValueLike[],
  valueType?: XOptionValueType,
): XOptionValue => {
  const matchingOption = options?.find(
    (option) => stringifyXOptionPrimitiveValue(option.value, option.valueType ?? valueType) === primitiveValue,
  )
  if (matchingOption) {
    return matchingOption.value
  }
  return parsePrefixedXOptionPrimitiveValue(primitiveValue)
}

export const getXOptionPrimitiveValue = (
  options: readonly XOptionValueLike[],
  value: XOptionValue | undefined,
  valueType?: XOptionValueType,
) => {
  if (typeof value === 'undefined') {
    return undefined
  }

  const primitiveValue = stringifyXOptionPrimitiveValue(value, valueType)
  return options
    .map((option) => stringifyXOptionPrimitiveValue(option.value, option.valueType ?? valueType))
    .find((optionValue) => optionValue === primitiveValue)
}
