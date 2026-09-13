import { useFFormContext } from '@/modules/form/core/context'
import { isPlainObject } from '@/utils'
import { omit as omitValues, pick as pickValues } from '@/utils/pick'
import type { ReactNode } from 'react'
import { useCallback, useEffect, useMemo, useState as useReactState, useRef } from 'react'
import {
  get as getByPath,
  type DeepPartialSkipArrayKey,
  type FieldPath,
  type FieldPathValue,
  type FieldPathValues,
  type FieldValues,
} from 'react-hook-form'
import type { UseFFormReturn } from './hook'

// ---------- Common option types ----------

export type FFormHandleOption<
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = {
  form?: UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput>
}

/**
 * Optional callback passed as the _second_ argument to `useFValues`. When provided, the hook subscribes silently (no
 * re-render) and the callback fires on every change with the same shape the hook would otherwise return; the hook
 * returns `undefined` in that mode.
 */
export type FFormSubscriptionCallback<TValue> = (value: TValue) => void

export type UseFValuesOptions = {
  disabled?: boolean
  exact?: boolean
  debounce?: number
}

type UseFValuesRawOptions = UseFValuesOptions & {
  /** Validate in the background, but keep returning original form values. */
  valid?: boolean
  parsed?: false
}

type UseFValuesParsedOptions = UseFValuesOptions & {
  /** - parsed: true implies valid: true and returns values from TTransformedValues. */
  parsed: true
  valid?: true
}

type UseFValuesNoSelector = {
  name?: undefined
  pick?: never
  omit?: never
}

type UseFValuesNameSelector<TName> = {
  name: TName
  pick?: never
  omit?: never
}

type UseFValuesPickSelector<TKey extends readonly PropertyKey[]> = {
  name?: never
  pick: readonly [...TKey]
  omit?: never
}

type UseFValuesOmitSelector<TKey extends readonly PropertyKey[]> = {
  name?: never
  pick?: never
  omit: readonly [...TKey]
}

export type UseFValuesValidResult<TOriginal, TParsed> =
  | {
      isValid: true
      parsed: TParsed
      original: TOriginal
    }
  | {
      isValid: false
      parsed: undefined
      original: TOriginal
    }

export type UseFValuesValidComputedResult<TComputed> =
  | {
      isValid: true
      computed: TComputed
    }
  | {
      isValid: false
      computed: undefined
    }

type UseFValuesInvalidTuple<TValues extends readonly unknown[]> = {
  [TKey in keyof TValues]: undefined
}

export type UseFValuesValidTupleResult<TParsed extends readonly unknown[], TOriginal> =
  | {
      isValid: true
      parsed: TParsed
      original: TOriginal
    }
  | {
      isValid: false
      parsed: UseFValuesInvalidTuple<TParsed>
      original: TOriginal
    }

type UseFValuesUndefinedPick<TKey extends PropertyKey> = {
  [TKeyItem in TKey]: undefined
}

export type UseFValuesValidPickResult<TValues, TKeys extends readonly PropertyKey[], TOriginal> =
  | {
      isValid: true
      parsed: Pick<TValues, Extract<TKeys[number], keyof TValues>>
      original: TOriginal
    }
  | {
      isValid: false
      parsed: UseFValuesUndefinedPick<TKeys[number]>
      original: TOriginal
    }

/**
 * Overload-rich signature for `useFValues` / `form.useValues`.
 *
 * Every shape exists as a pair:
 *
 * - `fn(props)` returns the result; the consumer component re-renders when the value changes.
 * - `fn(props, callback)` subscribes silently (no consumer re-render) and the callback fires with the same shape on every
 *   change; the call returns `undefined`.
 *
 * Shorthand: `fn(callback)` is equivalent to `fn({}, callback)` — subscribe to all values with no selector and no
 * `form` override.
 *
 * Generic resolution:
 *
 * - The outer `TFieldValuesDefault` / `TTransformedValuesDefault` parameters act as **defaults** for each overload's
 *   per-call generics. They are bound when the form constructs `form.useValues: UseFValues<TFV, TTV>`, so
 *   `form.useValues({ name: 'x' })` keeps `name` constrained to the form's field paths.
 * - When the type is used unbound (e.g. the exported `useFValues` is `UseFValues<FieldValues>`), each overload's per-call
 *   `TFieldValues` / `TTransformedValues` get inferred from the optional `form?` prop, giving the same end-to-end
 *   inference that `<FValues form={form} ... />` enjoys.
 * - With no `form` prop and no outer binding, the per-call generics fall back to the defaults (`FieldValues`), so usage
 *   degrades to permissive any-ish typing.
 */
export type UseFValues<
  TFieldValuesDefault extends FieldValues = FieldValues,
  TTransformedValuesDefault extends FieldValues = TFieldValuesDefault,
> = {
  // Shorthand: function-only argument, subscribe to all raw values.
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
  >(
    callback: FFormSubscriptionCallback<DeepPartialSkipArrayKey<TFieldValues>>,
  ): undefined

  // Raw values: no selector. Returns the original form object unless compute is provided.
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
  >(
    props?: UseFValuesNoSelector & {
      defaultValues?: NoInfer<DeepPartialSkipArrayKey<TFieldValues>>
      compute?: undefined
    } & UseFValuesRawOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
  ): DeepPartialSkipArrayKey<TFieldValues>
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
  >(
    props: UseFValuesNoSelector & {
      defaultValues?: NoInfer<DeepPartialSkipArrayKey<TFieldValues>>
      compute?: undefined
    } & UseFValuesRawOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
    callback: FFormSubscriptionCallback<DeepPartialSkipArrayKey<TFieldValues>>,
  ): undefined
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TComputeValue = unknown,
  >(
    props: UseFValuesNoSelector & {
      defaultValues?: NoInfer<DeepPartialSkipArrayKey<TFieldValues>>
      compute: (formValues: NoInfer<TFieldValues>) => TComputeValue
    } & UseFValuesRawOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
  ): TComputeValue
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TComputeValue = unknown,
  >(
    props: UseFValuesNoSelector & {
      defaultValues?: NoInfer<DeepPartialSkipArrayKey<TFieldValues>>
      compute: (formValues: NoInfer<TFieldValues>) => TComputeValue
    } & UseFValuesRawOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
    callback: FFormSubscriptionCallback<TComputeValue>,
  ): undefined
  <TFieldValues extends FieldValues = TFieldValuesDefault>(): DeepPartialSkipArrayKey<TFieldValues>

  // Raw values: name selector. Supports both scalar field paths and RHF tuple field paths.
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  >(
    props: UseFValuesNameSelector<TFieldName> & {
      defaultValues?: NoInfer<FieldPathValue<TFieldValues, TFieldName>>
      compute?: undefined
    } & UseFValuesRawOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
  ): FieldPathValue<TFieldValues, TFieldName>
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  >(
    props: UseFValuesNameSelector<TFieldName> & {
      defaultValues?: NoInfer<FieldPathValue<TFieldValues, TFieldName>>
      compute?: undefined
    } & UseFValuesRawOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
    callback: FFormSubscriptionCallback<FieldPathValue<TFieldValues, TFieldName>>,
  ): undefined
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
    TComputeValue = unknown,
  >(
    props: UseFValuesNameSelector<TFieldName> & {
      defaultValues?: NoInfer<FieldPathValue<TFieldValues, TFieldName>>
      compute: (fieldValue: NoInfer<FieldPathValue<TFieldValues, TFieldName>>) => TComputeValue
    } & UseFValuesRawOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
  ): TComputeValue
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
    TComputeValue = unknown,
  >(
    props: UseFValuesNameSelector<TFieldName> & {
      defaultValues?: NoInfer<FieldPathValue<TFieldValues, TFieldName>>
      compute: (fieldValue: NoInfer<FieldPathValue<TFieldValues, TFieldName>>) => TComputeValue
    } & UseFValuesRawOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
    callback: FFormSubscriptionCallback<TComputeValue>,
  ): undefined
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldNames extends readonly FieldPath<TFieldValues>[] = readonly FieldPath<TFieldValues>[],
  >(
    props: UseFValuesNameSelector<readonly [...TFieldNames]> & {
      defaultValues?: NoInfer<FieldPathValues<TFieldValues, TFieldNames>>
      compute?: undefined
    } & UseFValuesRawOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
  ): FieldPathValues<TFieldValues, TFieldNames>
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldNames extends readonly FieldPath<TFieldValues>[] = readonly FieldPath<TFieldValues>[],
  >(
    props: UseFValuesNameSelector<readonly [...TFieldNames]> & {
      defaultValues?: NoInfer<FieldPathValues<TFieldValues, TFieldNames>>
      compute?: undefined
    } & UseFValuesRawOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
    callback: FFormSubscriptionCallback<FieldPathValues<TFieldValues, TFieldNames>>,
  ): undefined
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldNames extends readonly FieldPath<TFieldValues>[] = readonly FieldPath<TFieldValues>[],
    TComputeValue = unknown,
  >(
    props: UseFValuesNameSelector<readonly [...TFieldNames]> & {
      defaultValues?: NoInfer<FieldPathValues<TFieldValues, TFieldNames>>
      compute: (fieldValue: NoInfer<FieldPathValues<TFieldValues, TFieldNames>>) => TComputeValue
    } & UseFValuesRawOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
  ): TComputeValue
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldNames extends readonly FieldPath<TFieldValues>[] = readonly FieldPath<TFieldValues>[],
    TComputeValue = unknown,
  >(
    props: UseFValuesNameSelector<readonly [...TFieldNames]> & {
      defaultValues?: NoInfer<FieldPathValues<TFieldValues, TFieldNames>>
      compute: (fieldValue: NoInfer<FieldPathValues<TFieldValues, TFieldNames>>) => TComputeValue
    } & UseFValuesRawOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
    callback: FFormSubscriptionCallback<TComputeValue>,
  ): undefined

  // Raw values: pick selector. Returns an object containing only the selected top-level keys.
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldKeys extends readonly Extract<keyof TFieldValues, string>[] = readonly Extract<keyof TFieldValues, string>[],
  >(
    props: UseFValuesPickSelector<TFieldKeys> & {
      defaultValues?: NoInfer<Pick<TFieldValues, TFieldKeys[number]>>
      compute?: undefined
    } & UseFValuesRawOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
  ): Pick<TFieldValues, TFieldKeys[number]>
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldKeys extends readonly Extract<keyof TFieldValues, string>[] = readonly Extract<keyof TFieldValues, string>[],
  >(
    props: UseFValuesPickSelector<TFieldKeys> & {
      defaultValues?: NoInfer<Pick<TFieldValues, TFieldKeys[number]>>
      compute?: undefined
    } & UseFValuesRawOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
    callback: FFormSubscriptionCallback<Pick<TFieldValues, TFieldKeys[number]>>,
  ): undefined
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldKeys extends readonly Extract<keyof TFieldValues, string>[] = readonly Extract<keyof TFieldValues, string>[],
    TComputeValue = unknown,
  >(
    props: UseFValuesPickSelector<TFieldKeys> & {
      defaultValues?: NoInfer<Pick<TFieldValues, TFieldKeys[number]>>
      compute: (fieldValue: NoInfer<Pick<TFieldValues, TFieldKeys[number]>>) => TComputeValue
    } & UseFValuesRawOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
  ): TComputeValue
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldKeys extends readonly Extract<keyof TFieldValues, string>[] = readonly Extract<keyof TFieldValues, string>[],
    TComputeValue = unknown,
  >(
    props: UseFValuesPickSelector<TFieldKeys> & {
      defaultValues?: NoInfer<Pick<TFieldValues, TFieldKeys[number]>>
      compute: (fieldValue: NoInfer<Pick<TFieldValues, TFieldKeys[number]>>) => TComputeValue
    } & UseFValuesRawOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
    callback: FFormSubscriptionCallback<TComputeValue>,
  ): undefined

  // Raw values: omit selector.
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldKeys extends readonly Extract<keyof TFieldValues, string>[] = readonly Extract<keyof TFieldValues, string>[],
  >(
    props: UseFValuesOmitSelector<TFieldKeys> & {
      defaultValues?: NoInfer<Omit<TFieldValues, TFieldKeys[number]>>
      compute?: undefined
    } & UseFValuesRawOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
  ): Omit<TFieldValues, TFieldKeys[number]>
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldKeys extends readonly Extract<keyof TFieldValues, string>[] = readonly Extract<keyof TFieldValues, string>[],
  >(
    props: UseFValuesOmitSelector<TFieldKeys> & {
      defaultValues?: NoInfer<Omit<TFieldValues, TFieldKeys[number]>>
      compute?: undefined
    } & UseFValuesRawOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
    callback: FFormSubscriptionCallback<Omit<TFieldValues, TFieldKeys[number]>>,
  ): undefined
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldKeys extends readonly Extract<keyof TFieldValues, string>[] = readonly Extract<keyof TFieldValues, string>[],
    TComputeValue = unknown,
  >(
    props: UseFValuesOmitSelector<TFieldKeys> & {
      defaultValues?: NoInfer<Omit<TFieldValues, TFieldKeys[number]>>
      compute: (fieldValue: NoInfer<Omit<TFieldValues, TFieldKeys[number]>>) => TComputeValue
    } & UseFValuesRawOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
  ): TComputeValue
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldKeys extends readonly Extract<keyof TFieldValues, string>[] = readonly Extract<keyof TFieldValues, string>[],
    TComputeValue = unknown,
  >(
    props: UseFValuesOmitSelector<TFieldKeys> & {
      defaultValues?: NoInfer<Omit<TFieldValues, TFieldKeys[number]>>
      compute: (fieldValue: NoInfer<Omit<TFieldValues, TFieldKeys[number]>>) => TComputeValue
    } & UseFValuesRawOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
    callback: FFormSubscriptionCallback<TComputeValue>,
  ): undefined

  // Parsed values: no selector.
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
  >(
    props: UseFValuesNoSelector & {
      defaultValues: NoInfer<TTransformedValues>
      compute?: undefined
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
  ): TTransformedValues
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
  >(
    props: UseFValuesNoSelector & {
      defaultValues: NoInfer<TTransformedValues>
      compute?: undefined
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
    callback: FFormSubscriptionCallback<TTransformedValues>,
  ): undefined
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
  >(
    props: UseFValuesNoSelector & {
      defaultValues?: undefined
      compute?: undefined
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
  ): UseFValuesValidResult<DeepPartialSkipArrayKey<TFieldValues>, TTransformedValues>
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
  >(
    props: UseFValuesNoSelector & {
      defaultValues?: undefined
      compute?: undefined
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
    callback: FFormSubscriptionCallback<
      UseFValuesValidResult<DeepPartialSkipArrayKey<TFieldValues>, TTransformedValues>
    >,
  ): undefined
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TComputeValue = unknown,
  >(
    props: UseFValuesNoSelector & {
      defaultValues: NoInfer<TTransformedValues>
      compute: (formValues: NoInfer<TTransformedValues>) => TComputeValue
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
  ): TComputeValue
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TComputeValue = unknown,
  >(
    props: UseFValuesNoSelector & {
      defaultValues: NoInfer<TTransformedValues>
      compute: (formValues: NoInfer<TTransformedValues>) => TComputeValue
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
    callback: FFormSubscriptionCallback<TComputeValue>,
  ): undefined
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TComputeValue = unknown,
  >(
    props: UseFValuesNoSelector & {
      defaultValues?: undefined
      compute: (formValues: NoInfer<TTransformedValues>) => TComputeValue
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
  ): UseFValuesValidComputedResult<TComputeValue>
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TComputeValue = unknown,
  >(
    props: UseFValuesNoSelector & {
      defaultValues?: undefined
      compute: (formValues: NoInfer<TTransformedValues>) => TComputeValue
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
    callback: FFormSubscriptionCallback<UseFValuesValidComputedResult<TComputeValue>>,
  ): undefined

  // Parsed values: name selector.
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldName extends FieldPath<TTransformedValues> = FieldPath<TTransformedValues>,
  >(
    props: UseFValuesNameSelector<TFieldName> & {
      defaultValues: NoInfer<FieldPathValue<TTransformedValues, TFieldName>>
      compute?: undefined
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
  ): FieldPathValue<TTransformedValues, TFieldName>
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldName extends FieldPath<TTransformedValues> = FieldPath<TTransformedValues>,
  >(
    props: UseFValuesNameSelector<TFieldName> & {
      defaultValues: NoInfer<FieldPathValue<TTransformedValues, TFieldName>>
      compute?: undefined
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
    callback: FFormSubscriptionCallback<FieldPathValue<TTransformedValues, TFieldName>>,
  ): undefined
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldName extends FieldPath<TTransformedValues> = FieldPath<TTransformedValues>,
  >(
    props: UseFValuesNameSelector<TFieldName> & {
      defaultValues?: undefined
      compute?: undefined
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
  ): UseFValuesValidResult<
    TFieldName extends FieldPath<TFieldValues> ? FieldPathValue<TFieldValues, TFieldName> : never,
    FieldPathValue<TTransformedValues, TFieldName>
  >
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldName extends FieldPath<TTransformedValues> = FieldPath<TTransformedValues>,
  >(
    props: UseFValuesNameSelector<TFieldName> & {
      defaultValues?: undefined
      compute?: undefined
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
    callback: FFormSubscriptionCallback<
      UseFValuesValidResult<
        TFieldName extends FieldPath<TFieldValues> ? FieldPathValue<TFieldValues, TFieldName> : never,
        FieldPathValue<TTransformedValues, TFieldName>
      >
    >,
  ): undefined
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldName extends FieldPath<TTransformedValues> = FieldPath<TTransformedValues>,
    TComputeValue = unknown,
  >(
    props: UseFValuesNameSelector<TFieldName> & {
      defaultValues: NoInfer<FieldPathValue<TTransformedValues, TFieldName>>
      compute: (fieldValue: NoInfer<FieldPathValue<TTransformedValues, TFieldName>>) => TComputeValue
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
  ): TComputeValue
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldName extends FieldPath<TTransformedValues> = FieldPath<TTransformedValues>,
    TComputeValue = unknown,
  >(
    props: UseFValuesNameSelector<TFieldName> & {
      defaultValues: NoInfer<FieldPathValue<TTransformedValues, TFieldName>>
      compute: (fieldValue: NoInfer<FieldPathValue<TTransformedValues, TFieldName>>) => TComputeValue
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
    callback: FFormSubscriptionCallback<TComputeValue>,
  ): undefined
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldName extends FieldPath<TTransformedValues> = FieldPath<TTransformedValues>,
    TComputeValue = unknown,
  >(
    props: UseFValuesNameSelector<TFieldName> & {
      defaultValues?: undefined
      compute: (fieldValue: NoInfer<FieldPathValue<TTransformedValues, TFieldName>>) => TComputeValue
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
  ): UseFValuesValidComputedResult<TComputeValue>
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldName extends FieldPath<TTransformedValues> = FieldPath<TTransformedValues>,
    TComputeValue = unknown,
  >(
    props: UseFValuesNameSelector<TFieldName> & {
      defaultValues?: undefined
      compute: (fieldValue: NoInfer<FieldPathValue<TTransformedValues, TFieldName>>) => TComputeValue
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
    callback: FFormSubscriptionCallback<UseFValuesValidComputedResult<TComputeValue>>,
  ): undefined
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldNames extends readonly FieldPath<TTransformedValues>[] = readonly FieldPath<TTransformedValues>[],
  >(
    props: UseFValuesNameSelector<readonly [...TFieldNames]> & {
      defaultValues: NoInfer<FieldPathValues<TTransformedValues, TFieldNames>>
      compute?: undefined
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
  ): FieldPathValues<TTransformedValues, TFieldNames>
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldNames extends readonly FieldPath<TTransformedValues>[] = readonly FieldPath<TTransformedValues>[],
  >(
    props: UseFValuesNameSelector<readonly [...TFieldNames]> & {
      defaultValues: NoInfer<FieldPathValues<TTransformedValues, TFieldNames>>
      compute?: undefined
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
    callback: FFormSubscriptionCallback<FieldPathValues<TTransformedValues, TFieldNames>>,
  ): undefined
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldNames extends readonly FieldPath<TTransformedValues>[] = readonly FieldPath<TTransformedValues>[],
  >(
    props: UseFValuesNameSelector<readonly [...TFieldNames]> & {
      defaultValues?: undefined
      compute?: undefined
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
  ): UseFValuesValidTupleResult<
    FieldPathValues<TTransformedValues, TFieldNames>,
    TFieldNames extends readonly FieldPath<TFieldValues>[] ? FieldPathValues<TFieldValues, TFieldNames> : never
  >
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldNames extends readonly FieldPath<TTransformedValues>[] = readonly FieldPath<TTransformedValues>[],
  >(
    props: UseFValuesNameSelector<readonly [...TFieldNames]> & {
      defaultValues?: undefined
      compute?: undefined
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
    callback: FFormSubscriptionCallback<
      UseFValuesValidTupleResult<
        FieldPathValues<TTransformedValues, TFieldNames>,
        TFieldNames extends readonly FieldPath<TFieldValues>[] ? FieldPathValues<TFieldValues, TFieldNames> : never
      >
    >,
  ): undefined
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldNames extends readonly FieldPath<TTransformedValues>[] = readonly FieldPath<TTransformedValues>[],
    TComputeValue = unknown,
  >(
    props: UseFValuesNameSelector<readonly [...TFieldNames]> & {
      defaultValues: NoInfer<FieldPathValues<TTransformedValues, TFieldNames>>
      compute: (fieldValue: NoInfer<FieldPathValues<TTransformedValues, TFieldNames>>) => TComputeValue
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
  ): TComputeValue
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldNames extends readonly FieldPath<TTransformedValues>[] = readonly FieldPath<TTransformedValues>[],
    TComputeValue = unknown,
  >(
    props: UseFValuesNameSelector<readonly [...TFieldNames]> & {
      defaultValues: NoInfer<FieldPathValues<TTransformedValues, TFieldNames>>
      compute: (fieldValue: NoInfer<FieldPathValues<TTransformedValues, TFieldNames>>) => TComputeValue
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
    callback: FFormSubscriptionCallback<TComputeValue>,
  ): undefined
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldNames extends readonly FieldPath<TTransformedValues>[] = readonly FieldPath<TTransformedValues>[],
    TComputeValue = unknown,
  >(
    props: UseFValuesNameSelector<readonly [...TFieldNames]> & {
      defaultValues?: undefined
      compute: (fieldValue: NoInfer<FieldPathValues<TTransformedValues, TFieldNames>>) => TComputeValue
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
  ): UseFValuesValidComputedResult<TComputeValue>
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldNames extends readonly FieldPath<TTransformedValues>[] = readonly FieldPath<TTransformedValues>[],
    TComputeValue = unknown,
  >(
    props: UseFValuesNameSelector<readonly [...TFieldNames]> & {
      defaultValues?: undefined
      compute: (fieldValue: NoInfer<FieldPathValues<TTransformedValues, TFieldNames>>) => TComputeValue
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
    callback: FFormSubscriptionCallback<UseFValuesValidComputedResult<TComputeValue>>,
  ): undefined

  // Parsed values: pick selector.
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldKeys extends readonly Extract<keyof TTransformedValues, string>[] = readonly Extract<
      keyof TTransformedValues,
      string
    >[],
  >(
    props: UseFValuesPickSelector<TFieldKeys> & {
      defaultValues: NoInfer<Pick<TTransformedValues, TFieldKeys[number]>>
      compute?: undefined
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
  ): Pick<TTransformedValues, TFieldKeys[number]>
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldKeys extends readonly Extract<keyof TTransformedValues, string>[] = readonly Extract<
      keyof TTransformedValues,
      string
    >[],
  >(
    props: UseFValuesPickSelector<TFieldKeys> & {
      defaultValues: NoInfer<Pick<TTransformedValues, TFieldKeys[number]>>
      compute?: undefined
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
    callback: FFormSubscriptionCallback<Pick<TTransformedValues, TFieldKeys[number]>>,
  ): undefined
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldKeys extends readonly Extract<keyof TTransformedValues, string>[] = readonly Extract<
      keyof TTransformedValues,
      string
    >[],
  >(
    props: UseFValuesPickSelector<TFieldKeys> & {
      defaultValues?: undefined
      compute?: undefined
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
  ): UseFValuesValidPickResult<
    TTransformedValues,
    TFieldKeys,
    Pick<TFieldValues, Extract<TFieldKeys[number], keyof TFieldValues>>
  >
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldKeys extends readonly Extract<keyof TTransformedValues, string>[] = readonly Extract<
      keyof TTransformedValues,
      string
    >[],
  >(
    props: UseFValuesPickSelector<TFieldKeys> & {
      defaultValues?: undefined
      compute?: undefined
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
    callback: FFormSubscriptionCallback<
      UseFValuesValidPickResult<
        TTransformedValues,
        TFieldKeys,
        Pick<TFieldValues, Extract<TFieldKeys[number], keyof TFieldValues>>
      >
    >,
  ): undefined
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldKeys extends readonly Extract<keyof TTransformedValues, string>[] = readonly Extract<
      keyof TTransformedValues,
      string
    >[],
    TComputeValue = unknown,
  >(
    props: UseFValuesPickSelector<TFieldKeys> & {
      defaultValues: NoInfer<Pick<TTransformedValues, TFieldKeys[number]>>
      compute: (fieldValue: NoInfer<Pick<TTransformedValues, TFieldKeys[number]>>) => TComputeValue
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
  ): TComputeValue
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldKeys extends readonly Extract<keyof TTransformedValues, string>[] = readonly Extract<
      keyof TTransformedValues,
      string
    >[],
    TComputeValue = unknown,
  >(
    props: UseFValuesPickSelector<TFieldKeys> & {
      defaultValues: NoInfer<Pick<TTransformedValues, TFieldKeys[number]>>
      compute: (fieldValue: NoInfer<Pick<TTransformedValues, TFieldKeys[number]>>) => TComputeValue
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
    callback: FFormSubscriptionCallback<TComputeValue>,
  ): undefined
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldKeys extends readonly Extract<keyof TTransformedValues, string>[] = readonly Extract<
      keyof TTransformedValues,
      string
    >[],
    TComputeValue = unknown,
  >(
    props: UseFValuesPickSelector<TFieldKeys> & {
      defaultValues?: undefined
      compute: (fieldValue: NoInfer<Pick<TTransformedValues, TFieldKeys[number]>>) => TComputeValue
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
  ): UseFValuesValidComputedResult<TComputeValue>
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldKeys extends readonly Extract<keyof TTransformedValues, string>[] = readonly Extract<
      keyof TTransformedValues,
      string
    >[],
    TComputeValue = unknown,
  >(
    props: UseFValuesPickSelector<TFieldKeys> & {
      defaultValues?: undefined
      compute: (fieldValue: NoInfer<Pick<TTransformedValues, TFieldKeys[number]>>) => TComputeValue
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
    callback: FFormSubscriptionCallback<UseFValuesValidComputedResult<TComputeValue>>,
  ): undefined

  // Parsed values: omit selector.
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldKeys extends readonly Extract<keyof TTransformedValues, string>[] = readonly Extract<
      keyof TTransformedValues,
      string
    >[],
  >(
    props: UseFValuesOmitSelector<TFieldKeys> & {
      defaultValues: NoInfer<Omit<TTransformedValues, TFieldKeys[number]>>
      compute?: undefined
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
  ): Omit<TTransformedValues, TFieldKeys[number]>
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldKeys extends readonly Extract<keyof TTransformedValues, string>[] = readonly Extract<
      keyof TTransformedValues,
      string
    >[],
  >(
    props: UseFValuesOmitSelector<TFieldKeys> & {
      defaultValues: NoInfer<Omit<TTransformedValues, TFieldKeys[number]>>
      compute?: undefined
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
    callback: FFormSubscriptionCallback<Omit<TTransformedValues, TFieldKeys[number]>>,
  ): undefined
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldKeys extends readonly Extract<keyof TTransformedValues, string>[] = readonly Extract<
      keyof TTransformedValues,
      string
    >[],
  >(
    props: UseFValuesOmitSelector<TFieldKeys> & {
      defaultValues?: undefined
      compute?: undefined
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
  ): UseFValuesValidResult<
    Omit<TFieldValues, Extract<TFieldKeys[number], keyof TFieldValues>>,
    Omit<TTransformedValues, TFieldKeys[number]>
  >
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldKeys extends readonly Extract<keyof TTransformedValues, string>[] = readonly Extract<
      keyof TTransformedValues,
      string
    >[],
  >(
    props: UseFValuesOmitSelector<TFieldKeys> & {
      defaultValues?: undefined
      compute?: undefined
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
    callback: FFormSubscriptionCallback<
      UseFValuesValidResult<
        Omit<TFieldValues, Extract<TFieldKeys[number], keyof TFieldValues>>,
        Omit<TTransformedValues, TFieldKeys[number]>
      >
    >,
  ): undefined
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldKeys extends readonly Extract<keyof TTransformedValues, string>[] = readonly Extract<
      keyof TTransformedValues,
      string
    >[],
    TComputeValue = unknown,
  >(
    props: UseFValuesOmitSelector<TFieldKeys> & {
      defaultValues: NoInfer<Omit<TTransformedValues, TFieldKeys[number]>>
      compute: (fieldValue: NoInfer<Omit<TTransformedValues, TFieldKeys[number]>>) => TComputeValue
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
  ): TComputeValue
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldKeys extends readonly Extract<keyof TTransformedValues, string>[] = readonly Extract<
      keyof TTransformedValues,
      string
    >[],
    TComputeValue = unknown,
  >(
    props: UseFValuesOmitSelector<TFieldKeys> & {
      defaultValues: NoInfer<Omit<TTransformedValues, TFieldKeys[number]>>
      compute: (fieldValue: NoInfer<Omit<TTransformedValues, TFieldKeys[number]>>) => TComputeValue
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
    callback: FFormSubscriptionCallback<TComputeValue>,
  ): undefined
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldKeys extends readonly Extract<keyof TTransformedValues, string>[] = readonly Extract<
      keyof TTransformedValues,
      string
    >[],
    TComputeValue = unknown,
  >(
    props: UseFValuesOmitSelector<TFieldKeys> & {
      defaultValues?: undefined
      compute: (fieldValue: NoInfer<Omit<TTransformedValues, TFieldKeys[number]>>) => TComputeValue
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
  ): UseFValuesValidComputedResult<TComputeValue>
  <
    TFieldValues extends FieldValues = TFieldValuesDefault,
    TTransformedValues extends FieldValues = TTransformedValuesDefault,
    TFieldKeys extends readonly Extract<keyof TTransformedValues, string>[] = readonly Extract<
      keyof TTransformedValues,
      string
    >[],
    TComputeValue = unknown,
  >(
    props: UseFValuesOmitSelector<TFieldKeys> & {
      defaultValues?: undefined
      compute: (fieldValue: NoInfer<Omit<TTransformedValues, TFieldKeys[number]>>) => TComputeValue
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any>,
    callback: FFormSubscriptionCallback<UseFValuesValidComputedResult<TComputeValue>>,
  ): undefined
}

// ---------- Shared snapshot type ----------

export type ValuesValidSnapshot<TFieldValues extends FieldValues, TTransformedValues> = {
  parsed: TTransformedValues
  original: TFieldValues
}

// ---------- Equality helpers ----------

const isShallowEqual = <TValue extends Record<PropertyKey, unknown>>(left: TValue, right: TValue) => {
  const leftKeys = Object.keys(left)
  const rightKeys = Object.keys(right)
  return leftKeys.length === rightKeys.length && leftKeys.every((key) => Object.is(left[key], right[key]))
}

const isWatchValueEqual = (left: unknown, right: unknown) => {
  if (Object.is(left, right)) {
    return true
  }
  if (Array.isArray(left) && Array.isArray(right)) {
    return left.length === right.length && left.every((value, index) => Object.is(value, right[index]))
  }
  if (isPlainObject(left) && isPlainObject(right)) {
    return isShallowEqual(left as Record<PropertyKey, unknown>, right as Record<PropertyKey, unknown>)
  }
  return false
}

// ---------- Internal: subscribe to raw values with selector + debounce ----------

type SubscribeRawValuesOptions = {
  name?: undefined | readonly FieldPath<any>[] | FieldPath<any>
  pick?: undefined | readonly string[]
  omit?: undefined | readonly string[]
  defaultValues?: unknown
  compute?: undefined | ((value: any) => unknown)
  disabled?: boolean
  exact?: boolean
  debounce?: number
}

function useSubscribedRawValues(
  form: UseFFormReturn<any, any, any>,
  props?: SubscribeRawValuesOptions,
  hasCallback = false,
) {
  const { debounce, disabled, exact } = props ?? {}
  const name = props?.name
  const pick = props?.pick
  const omit = props?.omit
  const defaultValues = props?.defaultValues
  const subscriptionName = name ?? pick
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const valueRef = useRef<unknown>(undefined)
  const callbackRef = useRef<((value: unknown) => void) | undefined>(undefined)

  const getValue = useCallback(
    (values: any) => {
      const value = pick
        ? pickValues(values, pick as never)
        : omit
          ? omitValues(values, omit as never)
          : name === undefined
            ? values
            : Array.isArray(name)
              ? name.map((fieldName) => getByPath(values, fieldName as string))
              : getByPath(values, name as string)
      return value
    },
    [name, omit, pick],
  )

  const [value, setValue] = useReactState(() => {
    const initialValue = getValue(form.getValues())
    return initialValue === undefined && props && 'defaultValues' in props ? defaultValues : initialValue
  })

  useEffect(() => {
    valueRef.current = value
  }, [value])

  useEffect(() => {
    if (disabled) {
      return
    }

    const syncValue = (nextValue: unknown, shouldDebounce: boolean) => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current)
        timeoutRef.current = undefined
      }

      const commit = () => {
        if (isWatchValueEqual(valueRef.current, nextValue)) {
          return
        }
        valueRef.current = nextValue
        if (hasCallback) {
          callbackRef.current?.(nextValue)
        } else {
          setValue(nextValue)
        }
      }

      if (shouldDebounce && debounce && debounce > 0) {
        timeoutRef.current = setTimeout(commit, debounce)
        return
      }

      commit()
    }

    syncValue(getValue(form.getValues()), false)

    const unsubscribe = form.subscribe({
      name: subscriptionName as never,
      exact,
      formState: { values: true },
      callback: ({ values }) => {
        syncValue(getValue(values), debounce !== undefined)
      },
    })

    return () => {
      unsubscribe()
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current)
        timeoutRef.current = undefined
      }
    }
  }, [debounce, disabled, exact, form, getValue, hasCallback, setValue, subscriptionName])

  return { value, callbackRef }
}

// ---------- Internal: compute wrapped/unwrapped values result ----------

function computeValuesResult(form: UseFFormReturn<any, any, any>, props: any, watchedOriginal: unknown) {
  const shouldReturnParsed = !!props?.parsed
  const shouldValidate = !!props?.valid || shouldReturnParsed
  const name = props?.name
  const pick = props?.pick
  const omit = props?.omit
  const hasDefaultValue = props && 'defaultValues' in props
  const defaultValues = props?.defaultValues
  const compute = props?.compute

  const selectObjectValues = (values: unknown) => {
    if (pick) {
      return pickValues(values, pick as never)
    }
    if (omit) {
      return omitValues(values, omit as never)
    }
    return values
  }

  const original = name !== undefined ? form.getValues() : (selectObjectValues(watchedOriginal) as unknown)
  const parsed = shouldValidate ? form._parseValues(form.getValues()) : undefined

  if (!shouldReturnParsed) {
    const value = watchedOriginal === undefined && hasDefaultValue ? defaultValues : watchedOriginal
    return compute ? compute(value) : value
  }

  const isValid = !!parsed
  const prevParsed = form._lastValuesValidRef.current?.parsed

  if (!parsed && !prevParsed) {
    if (!hasDefaultValue) {
      if (compute) {
        return { isValid, computed: undefined }
      }
      if (Array.isArray(name)) {
        const undefinedValues = Array.from(name, () => undefined)
        return {
          isValid,
          parsed: undefinedValues,
          original: name.map((fieldName) => getByPath(original, fieldName as string)),
        }
      }
      if (pick) {
        const undefinedPick: Record<string, undefined> = {}
        for (const key of pick) {
          undefinedPick[key as string] = undefined
        }
        return {
          isValid,
          parsed: undefined,
          original: pickValues(original, pick as never),
        }
      }
      if (omit) {
        const omitted = omitValues(original, omit as never)
        return {
          isValid,
          parsed: omitted,
          original: omitted,
        }
      }
      return { isValid, parsed: undefined, original: undefined }
    }

    const value = pick
      ? pickValues(defaultValues, pick as never)
      : omit
        ? omitValues(defaultValues, omit as never)
        : name === undefined
          ? defaultValues
          : Array.isArray(name)
            ? name.map((fieldName) => getByPath(defaultValues, fieldName as string))
            : defaultValues
    if (compute) {
      return compute(value)
    }
    return value
  }

  const parsedOrPrevParsed = parsed ?? prevParsed

  const value = pick
    ? pickValues(parsedOrPrevParsed, pick as never)
    : omit
      ? omitValues(parsedOrPrevParsed, omit as never)
      : name === undefined
        ? parsedOrPrevParsed
        : Array.isArray(name)
          ? name.map((fieldName) => getByPath(parsedOrPrevParsed, fieldName as string))
          : typeof name === 'string'
            ? getByPath(parsedOrPrevParsed, name)
            : undefined
  if (compute) {
    const computed = compute(value)
    if (hasDefaultValue) {
      return computed
    }
    return { isValid, computed }
  }
  if (hasDefaultValue) {
    return value
  }
  return { isValid, parsed: value, original }
}

// ---------- Public hook ----------

function useFValuesImpl(propsOrCallback?: any, callbackArg?: (value: unknown) => void): unknown {
  // Shorthand: `useValues(callback)` is equivalent to `useValues({}, callback)`.
  const isShorthand = typeof propsOrCallback === 'function'
  const propsInput = isShorthand ? (undefined as any) : propsOrCallback
  const callback = (isShorthand ? propsOrCallback : callbackArg) as ((value: unknown) => void) | undefined
  const form = useFFormContext({ form: propsInput?.form }) as UseFFormReturn<any, any, any>
  const hasCallback = !!callback
  const { value: watchedOriginal, callbackRef } = useSubscribedRawValues(
    form,
    propsInput as SubscribeRawValuesOptions | undefined,
    hasCallback,
  )

  useEffect(() => {
    if (callback) {
      callbackRef.current = (next) => {
        const result = computeValuesResult(form, propsInput, next)
        callback(result)
      }
    } else {
      callbackRef.current = undefined
    }
  })

  const result = useMemo(
    () => (hasCallback ? undefined : computeValuesResult(form, propsInput, watchedOriginal)),
    [form, propsInput, watchedOriginal, hasCallback],
  )

  return result
}

export const useFValues = useFValuesImpl as UseFValues

// FValues

type FValuesRenderer<TValue> = (values: TValue) => ReactNode

type FValuesRenderOption<TValue> =
  | {
      render: FValuesRenderer<TValue>
      children?: never
    }
  | {
      children: FValuesRenderer<TValue>
      render?: never
    }

/**
 * Overload-rich signature for `<FValues />` — the JSX counterpart of `useFValues`.
 *
 * Mirrors every shape from {@link UseFValues} (callback variants excluded; FValues is render-only). Each overload is
 * generic on `<TFieldValues, TTransformedValues>` so that `form?` flows the typing through the optional render prop.
 * When `form` is omitted, the generics default to `FieldValues`, which falls back to permissive `any` typing — the
 * component still works against the surrounding `FForm` context.
 */
export type FValues = {
  // Raw values: no selector.
  <TFieldValues extends FieldValues = FieldValues, TTransformedValues extends FieldValues = TFieldValues>(
    props: UseFValuesNoSelector & {
      defaultValues?: NoInfer<DeepPartialSkipArrayKey<TFieldValues>>
      compute?: undefined
    } & UseFValuesRawOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any> &
      FValuesRenderOption<DeepPartialSkipArrayKey<TFieldValues>>,
  ): ReactNode
  <
    TFieldValues extends FieldValues = FieldValues,
    TTransformedValues extends FieldValues = TFieldValues,
    TComputeValue = unknown,
  >(
    props: UseFValuesNoSelector & {
      defaultValues?: NoInfer<DeepPartialSkipArrayKey<TFieldValues>>
      compute: (formValues: NoInfer<TFieldValues>) => TComputeValue
    } & UseFValuesRawOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any> &
      FValuesRenderOption<TComputeValue>,
  ): ReactNode

  // Raw values: name selector. Supports both scalar field paths and RHF tuple field paths.
  <
    TFieldValues extends FieldValues = FieldValues,
    TTransformedValues extends FieldValues = TFieldValues,
    TFieldName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  >(
    props: UseFValuesNameSelector<TFieldName> & {
      defaultValues?: NoInfer<FieldPathValue<TFieldValues, TFieldName>>
      compute?: undefined
    } & UseFValuesRawOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any> &
      FValuesRenderOption<FieldPathValue<TFieldValues, TFieldName>>,
  ): ReactNode
  <
    TFieldValues extends FieldValues = FieldValues,
    TTransformedValues extends FieldValues = TFieldValues,
    TFieldName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
    TComputeValue = unknown,
  >(
    props: UseFValuesNameSelector<TFieldName> & {
      defaultValues?: NoInfer<FieldPathValue<TFieldValues, TFieldName>>
      compute: (fieldValue: NoInfer<FieldPathValue<TFieldValues, TFieldName>>) => TComputeValue
    } & UseFValuesRawOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any> &
      FValuesRenderOption<TComputeValue>,
  ): ReactNode
  <
    TFieldValues extends FieldValues = FieldValues,
    TTransformedValues extends FieldValues = TFieldValues,
    TFieldNames extends readonly FieldPath<TFieldValues>[] = readonly FieldPath<TFieldValues>[],
  >(
    props: UseFValuesNameSelector<readonly [...TFieldNames]> & {
      defaultValues?: NoInfer<FieldPathValues<TFieldValues, TFieldNames>>
      compute?: undefined
    } & UseFValuesRawOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any> &
      FValuesRenderOption<FieldPathValues<TFieldValues, TFieldNames>>,
  ): ReactNode
  <
    TFieldValues extends FieldValues = FieldValues,
    TTransformedValues extends FieldValues = TFieldValues,
    TFieldNames extends readonly FieldPath<TFieldValues>[] = readonly FieldPath<TFieldValues>[],
    TComputeValue = unknown,
  >(
    props: UseFValuesNameSelector<readonly [...TFieldNames]> & {
      defaultValues?: NoInfer<FieldPathValues<TFieldValues, TFieldNames>>
      compute: (fieldValue: NoInfer<FieldPathValues<TFieldValues, TFieldNames>>) => TComputeValue
    } & UseFValuesRawOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any> &
      FValuesRenderOption<TComputeValue>,
  ): ReactNode

  // Raw values: pick selector. Returns an object containing only the selected top-level keys.
  <
    TFieldValues extends FieldValues = FieldValues,
    TTransformedValues extends FieldValues = TFieldValues,
    TFieldKeys extends readonly Extract<keyof TFieldValues, string>[] = readonly Extract<keyof TFieldValues, string>[],
  >(
    props: UseFValuesPickSelector<TFieldKeys> & {
      defaultValues?: NoInfer<Pick<TFieldValues, TFieldKeys[number]>>
      compute?: undefined
    } & UseFValuesRawOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any> &
      FValuesRenderOption<Pick<TFieldValues, TFieldKeys[number]>>,
  ): ReactNode
  <
    TFieldValues extends FieldValues = FieldValues,
    TTransformedValues extends FieldValues = TFieldValues,
    TFieldKeys extends readonly Extract<keyof TFieldValues, string>[] = readonly Extract<keyof TFieldValues, string>[],
    TComputeValue = unknown,
  >(
    props: UseFValuesPickSelector<TFieldKeys> & {
      defaultValues?: NoInfer<Pick<TFieldValues, TFieldKeys[number]>>
      compute: (fieldValue: NoInfer<Pick<TFieldValues, TFieldKeys[number]>>) => TComputeValue
    } & UseFValuesRawOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any> &
      FValuesRenderOption<TComputeValue>,
  ): ReactNode

  // Raw values: omit selector.
  <
    TFieldValues extends FieldValues = FieldValues,
    TTransformedValues extends FieldValues = TFieldValues,
    TFieldKeys extends readonly Extract<keyof TFieldValues, string>[] = readonly Extract<keyof TFieldValues, string>[],
  >(
    props: UseFValuesOmitSelector<TFieldKeys> & {
      defaultValues?: NoInfer<Omit<TFieldValues, TFieldKeys[number]>>
      compute?: undefined
    } & UseFValuesRawOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any> &
      FValuesRenderOption<Omit<TFieldValues, TFieldKeys[number]>>,
  ): ReactNode
  <
    TFieldValues extends FieldValues = FieldValues,
    TTransformedValues extends FieldValues = TFieldValues,
    TFieldKeys extends readonly Extract<keyof TFieldValues, string>[] = readonly Extract<keyof TFieldValues, string>[],
    TComputeValue = unknown,
  >(
    props: UseFValuesOmitSelector<TFieldKeys> & {
      defaultValues?: NoInfer<Omit<TFieldValues, TFieldKeys[number]>>
      compute: (fieldValue: NoInfer<Omit<TFieldValues, TFieldKeys[number]>>) => TComputeValue
    } & UseFValuesRawOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any> &
      FValuesRenderOption<TComputeValue>,
  ): ReactNode

  // Parsed values: no selector.
  <TFieldValues extends FieldValues = FieldValues, TTransformedValues extends FieldValues = TFieldValues>(
    props: UseFValuesNoSelector & {
      defaultValues: NoInfer<TTransformedValues>
      compute?: undefined
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any> &
      FValuesRenderOption<TTransformedValues>,
  ): ReactNode
  <TFieldValues extends FieldValues = FieldValues, TTransformedValues extends FieldValues = TFieldValues>(
    props: UseFValuesNoSelector & {
      defaultValues?: undefined
      compute?: undefined
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any> &
      FValuesRenderOption<UseFValuesValidResult<DeepPartialSkipArrayKey<TFieldValues>, TTransformedValues>>,
  ): ReactNode
  <
    TFieldValues extends FieldValues = FieldValues,
    TTransformedValues extends FieldValues = TFieldValues,
    TComputeValue = unknown,
  >(
    props: UseFValuesNoSelector & {
      defaultValues: NoInfer<TTransformedValues>
      compute: (formValues: NoInfer<TTransformedValues>) => TComputeValue
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any> &
      FValuesRenderOption<TComputeValue>,
  ): ReactNode
  <
    TFieldValues extends FieldValues = FieldValues,
    TTransformedValues extends FieldValues = TFieldValues,
    TComputeValue = unknown,
  >(
    props: UseFValuesNoSelector & {
      defaultValues?: undefined
      compute: (formValues: NoInfer<TTransformedValues>) => TComputeValue
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any> &
      FValuesRenderOption<UseFValuesValidComputedResult<TComputeValue>>,
  ): ReactNode

  // Parsed values: name selector.
  <
    TFieldValues extends FieldValues = FieldValues,
    TTransformedValues extends FieldValues = TFieldValues,
    TFieldName extends FieldPath<TTransformedValues> = FieldPath<TTransformedValues>,
  >(
    props: UseFValuesNameSelector<TFieldName> & {
      defaultValues: NoInfer<FieldPathValue<TTransformedValues, TFieldName>>
      compute?: undefined
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any> &
      FValuesRenderOption<FieldPathValue<TTransformedValues, TFieldName>>,
  ): ReactNode
  <
    TFieldValues extends FieldValues = FieldValues,
    TTransformedValues extends FieldValues = TFieldValues,
    TFieldName extends FieldPath<TTransformedValues> = FieldPath<TTransformedValues>,
  >(
    props: UseFValuesNameSelector<TFieldName> & {
      defaultValues?: undefined
      compute?: undefined
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any> &
      FValuesRenderOption<
        UseFValuesValidResult<
          TFieldName extends FieldPath<TFieldValues> ? FieldPathValue<TFieldValues, TFieldName> : never,
          FieldPathValue<TTransformedValues, TFieldName>
        >
      >,
  ): ReactNode
  <
    TFieldValues extends FieldValues = FieldValues,
    TTransformedValues extends FieldValues = TFieldValues,
    TFieldName extends FieldPath<TTransformedValues> = FieldPath<TTransformedValues>,
    TComputeValue = unknown,
  >(
    props: UseFValuesNameSelector<TFieldName> & {
      defaultValues: NoInfer<FieldPathValue<TTransformedValues, TFieldName>>
      compute: (fieldValue: NoInfer<FieldPathValue<TTransformedValues, TFieldName>>) => TComputeValue
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any> &
      FValuesRenderOption<TComputeValue>,
  ): ReactNode
  <
    TFieldValues extends FieldValues = FieldValues,
    TTransformedValues extends FieldValues = TFieldValues,
    TFieldName extends FieldPath<TTransformedValues> = FieldPath<TTransformedValues>,
    TComputeValue = unknown,
  >(
    props: UseFValuesNameSelector<TFieldName> & {
      defaultValues?: undefined
      compute: (fieldValue: NoInfer<FieldPathValue<TTransformedValues, TFieldName>>) => TComputeValue
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any> &
      FValuesRenderOption<UseFValuesValidComputedResult<TComputeValue>>,
  ): ReactNode
  <
    TFieldValues extends FieldValues = FieldValues,
    TTransformedValues extends FieldValues = TFieldValues,
    TFieldNames extends readonly FieldPath<TTransformedValues>[] = readonly FieldPath<TTransformedValues>[],
  >(
    props: UseFValuesNameSelector<readonly [...TFieldNames]> & {
      defaultValues: NoInfer<FieldPathValues<TTransformedValues, TFieldNames>>
      compute?: undefined
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any> &
      FValuesRenderOption<FieldPathValues<TTransformedValues, TFieldNames>>,
  ): ReactNode
  <
    TFieldValues extends FieldValues = FieldValues,
    TTransformedValues extends FieldValues = TFieldValues,
    TFieldNames extends readonly FieldPath<TTransformedValues>[] = readonly FieldPath<TTransformedValues>[],
  >(
    props: UseFValuesNameSelector<readonly [...TFieldNames]> & {
      defaultValues?: undefined
      compute?: undefined
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any> &
      FValuesRenderOption<
        UseFValuesValidTupleResult<
          FieldPathValues<TTransformedValues, TFieldNames>,
          TFieldNames extends readonly FieldPath<TFieldValues>[] ? FieldPathValues<TFieldValues, TFieldNames> : never
        >
      >,
  ): ReactNode
  <
    TFieldValues extends FieldValues = FieldValues,
    TTransformedValues extends FieldValues = TFieldValues,
    TFieldNames extends readonly FieldPath<TTransformedValues>[] = readonly FieldPath<TTransformedValues>[],
    TComputeValue = unknown,
  >(
    props: UseFValuesNameSelector<readonly [...TFieldNames]> & {
      defaultValues: NoInfer<FieldPathValues<TTransformedValues, TFieldNames>>
      compute: (fieldValue: NoInfer<FieldPathValues<TTransformedValues, TFieldNames>>) => TComputeValue
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any> &
      FValuesRenderOption<TComputeValue>,
  ): ReactNode
  <
    TFieldValues extends FieldValues = FieldValues,
    TTransformedValues extends FieldValues = TFieldValues,
    TFieldNames extends readonly FieldPath<TTransformedValues>[] = readonly FieldPath<TTransformedValues>[],
    TComputeValue = unknown,
  >(
    props: UseFValuesNameSelector<readonly [...TFieldNames]> & {
      defaultValues?: undefined
      compute: (fieldValue: NoInfer<FieldPathValues<TTransformedValues, TFieldNames>>) => TComputeValue
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any> &
      FValuesRenderOption<UseFValuesValidComputedResult<TComputeValue>>,
  ): ReactNode

  // Parsed values: pick selector.
  <
    TFieldValues extends FieldValues = FieldValues,
    TTransformedValues extends FieldValues = TFieldValues,
    TFieldKeys extends readonly Extract<keyof TTransformedValues, string>[] = readonly Extract<
      keyof TTransformedValues,
      string
    >[],
  >(
    props: UseFValuesPickSelector<TFieldKeys> & {
      defaultValues: NoInfer<Pick<TTransformedValues, TFieldKeys[number]>>
      compute?: undefined
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any> &
      FValuesRenderOption<Pick<TTransformedValues, TFieldKeys[number]>>,
  ): ReactNode
  <
    TFieldValues extends FieldValues = FieldValues,
    TTransformedValues extends FieldValues = TFieldValues,
    TFieldKeys extends readonly Extract<keyof TTransformedValues, string>[] = readonly Extract<
      keyof TTransformedValues,
      string
    >[],
  >(
    props: UseFValuesPickSelector<TFieldKeys> & {
      defaultValues?: undefined
      compute?: undefined
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any> &
      FValuesRenderOption<
        UseFValuesValidPickResult<
          TTransformedValues,
          TFieldKeys,
          Pick<TFieldValues, Extract<TFieldKeys[number], keyof TFieldValues>>
        >
      >,
  ): ReactNode
  <
    TFieldValues extends FieldValues = FieldValues,
    TTransformedValues extends FieldValues = TFieldValues,
    TFieldKeys extends readonly Extract<keyof TTransformedValues, string>[] = readonly Extract<
      keyof TTransformedValues,
      string
    >[],
    TComputeValue = unknown,
  >(
    props: UseFValuesPickSelector<TFieldKeys> & {
      defaultValues: NoInfer<Pick<TTransformedValues, TFieldKeys[number]>>
      compute: (fieldValue: NoInfer<Pick<TTransformedValues, TFieldKeys[number]>>) => TComputeValue
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any> &
      FValuesRenderOption<TComputeValue>,
  ): ReactNode
  <
    TFieldValues extends FieldValues = FieldValues,
    TTransformedValues extends FieldValues = TFieldValues,
    TFieldKeys extends readonly Extract<keyof TTransformedValues, string>[] = readonly Extract<
      keyof TTransformedValues,
      string
    >[],
    TComputeValue = unknown,
  >(
    props: UseFValuesPickSelector<TFieldKeys> & {
      defaultValues?: undefined
      compute: (fieldValue: NoInfer<Pick<TTransformedValues, TFieldKeys[number]>>) => TComputeValue
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any> &
      FValuesRenderOption<UseFValuesValidComputedResult<TComputeValue>>,
  ): ReactNode

  // Parsed values: omit selector.
  <
    TFieldValues extends FieldValues = FieldValues,
    TTransformedValues extends FieldValues = TFieldValues,
    TFieldKeys extends readonly Extract<keyof TTransformedValues, string>[] = readonly Extract<
      keyof TTransformedValues,
      string
    >[],
  >(
    props: UseFValuesOmitSelector<TFieldKeys> & {
      defaultValues: NoInfer<Omit<TTransformedValues, TFieldKeys[number]>>
      compute?: undefined
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any> &
      FValuesRenderOption<Omit<TTransformedValues, TFieldKeys[number]>>,
  ): ReactNode
  <
    TFieldValues extends FieldValues = FieldValues,
    TTransformedValues extends FieldValues = TFieldValues,
    TFieldKeys extends readonly Extract<keyof TTransformedValues, string>[] = readonly Extract<
      keyof TTransformedValues,
      string
    >[],
  >(
    props: UseFValuesOmitSelector<TFieldKeys> & {
      defaultValues?: undefined
      compute?: undefined
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any> &
      FValuesRenderOption<
        UseFValuesValidResult<
          Omit<TFieldValues, Extract<TFieldKeys[number], keyof TFieldValues>>,
          Omit<TTransformedValues, TFieldKeys[number]>
        >
      >,
  ): ReactNode
  <
    TFieldValues extends FieldValues = FieldValues,
    TTransformedValues extends FieldValues = TFieldValues,
    TFieldKeys extends readonly Extract<keyof TTransformedValues, string>[] = readonly Extract<
      keyof TTransformedValues,
      string
    >[],
    TComputeValue = unknown,
  >(
    props: UseFValuesOmitSelector<TFieldKeys> & {
      defaultValues: NoInfer<Omit<TTransformedValues, TFieldKeys[number]>>
      compute: (fieldValue: NoInfer<Omit<TTransformedValues, TFieldKeys[number]>>) => TComputeValue
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any> &
      FValuesRenderOption<TComputeValue>,
  ): ReactNode
  <
    TFieldValues extends FieldValues = FieldValues,
    TTransformedValues extends FieldValues = TFieldValues,
    TFieldKeys extends readonly Extract<keyof TTransformedValues, string>[] = readonly Extract<
      keyof TTransformedValues,
      string
    >[],
    TComputeValue = unknown,
  >(
    props: UseFValuesOmitSelector<TFieldKeys> & {
      defaultValues?: undefined
      compute: (fieldValue: NoInfer<Omit<TTransformedValues, TFieldKeys[number]>>) => TComputeValue
    } & UseFValuesParsedOptions &
      FFormHandleOption<TFieldValues, TTransformedValues, any> &
      FValuesRenderOption<UseFValuesValidComputedResult<TComputeValue>>,
  ): ReactNode
}

function FValuesImpl(props: {
  render?: FValuesRenderer<unknown>
  children?: FValuesRenderer<unknown>
  [key: string]: unknown
}): ReactNode {
  const { children, render, ...valuesProps } = props
  const values = useFValues(valuesProps as never)
  const renderValues = (render ?? children) as FValuesRenderer<unknown>
  return renderValues(values)
}

export const FValues = FValuesImpl as FValues
