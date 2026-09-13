import { useEffect, useRef } from 'react'
import type { FieldPath, FieldValues, FormState, ReadFormState } from 'react-hook-form'
import { useFFormContext } from './context'
import type { UseFFormReturn } from './hook'

/**
 * Same payload shape as RHF's `subscribe`, except the form-owning component is implicit and the unsubscribe is handled
 * by `useEffect` internally — so the hook returns nothing.
 *
 * Mirrors `UseFormSubscribe<TFieldValues>` from `react-hook-form` 1:1 for the input.
 */
export type UseFFormSubscribe<TFieldValues extends FieldValues = FieldValues> = <
  TFieldNames extends readonly FieldPath<TFieldValues>[],
>(
  payload: {
    name?: readonly [...TFieldNames] | TFieldNames[number]
    formState?: Partial<ReadFormState>
    exact?: boolean
    callback: (
      data: Partial<FormState<TFieldValues>> & {
        values: TFieldValues
        name?: string
        type?: string
      },
    ) => void
  } & { form?: UseFFormReturn<TFieldValues, any, any> },
) => void

/**
 * Subscribe to `form.subscribe` events for the lifetime of the hosting component without managing the unsubscribe
 * yourself. The `callback` is read via a ref so it can change every render without re-subscribing; `name` / `formState`
 * / `exact` resubscribe on identity change.
 *
 * @example
 *   form.useSubscribe({
 *     formState: { values: true },
 *     callback: ({ values }) => console.info(values),
 *   })
 */
export const useFFormSubscribe: UseFFormSubscribe<any> = (payload) => {
  const { form: formProvided, callback, name, formState, exact } = payload
  const form = useFFormContext({ form: formProvided })

  const callbackRef = useRef(callback)
  useEffect(() => {
    callbackRef.current = callback
  })

  // Stable keys so a fresh `name` / `formState` array or object literal on every render doesn't
  // tear down and re-create the subscription. Identity changes in those fields *do* resubscribe.
  const nameKey = Array.isArray(name) ? name.join('\0') : typeof name === 'string' ? name : ''
  const formStateKey = formState
    ? Object.keys(formState)
        .filter((k) => (formState as Record<string, unknown>)[k] === true)
        .sort()
        .join('\0')
    : ''
  const exactKey = exact ? '1' : '0'

  useEffect(() => {
    const unsubscribe = form.subscribe({
      name: name as never,
      exact,
      formState,
      callback: (data) => callbackRef.current(data as never),
    })
    return unsubscribe
  }, [form, nameKey, formStateKey, exactKey])
}
