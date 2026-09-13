import { useFFormContext } from '@/modules/form/core/context'
import { useMemo } from 'react'
import {
  Controller,
  useController,
  type ControllerFieldState,
  type ControllerRenderProps,
  type FieldPath,
  type FieldValues,
  type UseControllerProps,
  type UseControllerReturn,
  type UseFormStateReturn,
} from 'react-hook-form'
import type { UseFFormReturn } from './hook'

export type FControllerRenderProps<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = {
  field: ControllerRenderProps<TFieldValues, TName>
  fieldState: ControllerFieldState
  formState: UseFormStateReturn<TFieldValues>
  id: string
  form: UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput>
}

export type FControllerProps<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = {
  id?: string
  render: (props: FControllerRenderProps<TFieldValues, TName, TTransformedValues, TSubmitOutput>) => React.ReactElement
  form?: UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput>
  // NOTE: `disabled` is intentionally omitted from RHF's `UseControllerProps` here.
  // Passing `disabled` into RHF's controller marks the field as disabled internally
  // and causes its value to be stripped from `handleSubmit` payload. We always treat
  // `disabled` as UI-only at the field layer above; never plumb it into RHF.
} & Omit<UseControllerProps<TFieldValues, TName, TTransformedValues>, 'control' | 'disabled'>

export function FController<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>(props: FControllerProps<TFieldValues, TName, TTransformedValues, TSubmitOutput>) {
  const { render, id: idProvided, form: formProvided, ...restProps } = props
  const form = useFFormContext<TFieldValues, TTransformedValues, TSubmitOutput>({ form: formProvided })

  return (
    <Controller
      {...restProps}
      control={form.control}
      render={({ field, fieldState, formState }) => {
        const id = idProvided || (form.id ? `${form.id}-${field.name}` : field.name)
        return render({
          field,
          fieldState,
          formState,
          id,
          form,
        })
      }}
    />
  )
}

export type UseFControllerProps<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = Omit<UseControllerProps<TFieldValues, TName, TTransformedValues>, 'control' | 'disabled'> & {
  form?: UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput>
  id?: string
}

export type UseFControllerReturn<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = UseControllerReturn<TFieldValues, TName> & {
  form: UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput>
  id: string
}

export function useFController<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>(
  props: UseFControllerProps<TFieldValues, TName, TTransformedValues, TSubmitOutput>,
): UseFControllerReturn<TFieldValues, TName, TTransformedValues, TSubmitOutput> {
  const { form: formProvided, id: idProvided, ...restProps } = props
  const form = useFFormContext<TFieldValues, TTransformedValues, TSubmitOutput>({ form: formProvided })
  const controller = useController<TFieldValues, TName, TTransformedValues>({ ...restProps, control: form.control })
  const id = idProvided || (form.id ? `${form.id}-${controller.field.name}` : controller.field.name)
  return useMemo(
    () => ({
      ...controller,
      form,
      id,
    }),
    [controller, form, id],
  )
}
