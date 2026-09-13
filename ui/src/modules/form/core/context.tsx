import type { ReactNode } from 'react'
import { createContext, useContext } from 'react'
import type { FieldValues } from 'react-hook-form'
import type { AnyUseFFormReturn, UseFFormReturn } from './hook'

export const FFormContext = createContext<AnyUseFFormReturn | undefined>(undefined)

export type UseFFormContextProps<
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = {
  /** Explicit form handle that wins over the surrounding `<FFormProvider>` if present. */
  form?: UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput>
  /** When `true`, returns `undefined` instead of throwing if no form is found. */
  optional?: boolean
}

export function useFFormContext<
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>(props?: {
  optional?: false
  form?: UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput>
}): UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput>
export function useFFormContext<
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>(props?: {
  optional?: boolean
  form: UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput>
}): UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput>
export function useFFormContext<
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>(props?: {
  optional: true
  form?: undefined
}): UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput> | undefined
export function useFFormContext<
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>(
  props?: UseFFormContextProps<TFieldValues, TTransformedValues, TSubmitOutput>,
): UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput> | undefined {
  const ctx = useContext(FFormContext)
  const form = props?.form ?? (ctx as UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput> | undefined)
  if (!form) {
    if (props?.optional) {
      return undefined
    }
    throw new Error('useFFormContext: no `form` passed and no <FForm> / <FFormProvider> in the tree')
  }
  return form
}

export const FFormContextConsumer = <
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>({
  children,
}: {
  children: (form: UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput>) => ReactNode
}): ReactNode => {
  const form = useFFormContext<TFieldValues, TTransformedValues, TSubmitOutput>()
  return children(form)
}
