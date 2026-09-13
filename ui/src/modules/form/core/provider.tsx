import { FFormContext } from '@/modules/form/core/context'
import type { UseFFormReturn, UseFFormProps } from '@/modules/form/core/hook'
import { useFForm } from '@/modules/form/core/hook'
import { FLayout, type FLayoutProps } from '@/modules/form/core/layout'
import { type ReactElement, type ReactNode } from 'react'
import { FormProvider, type FieldValues } from 'react-hook-form'

// form

export type FFormProviderBaseProps<
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = {
  children?: ReactNode | ((form: UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput>) => ReactNode)
}

export type FFormProviderWithInstance<
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = FFormProviderBaseProps<TFieldValues, TTransformedValues, TSubmitOutput> & {
  form: UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput>
}
export type FFormProviderWithSettings<
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = FFormProviderBaseProps<TFieldValues, TTransformedValues, TSubmitOutput> &
  UseFFormProps<TFieldValues, TTransformedValues, TSubmitOutput> & {
    form?: never
  }
export type FFormProviderProps<
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> =
  | FFormProviderWithInstance<TFieldValues, TTransformedValues, TSubmitOutput>
  | FFormProviderWithSettings<TFieldValues, TTransformedValues, TSubmitOutput>

const FFormProviderWithInstance = <
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>(
  props: FFormProviderWithInstance<TFieldValues, TTransformedValues, TSubmitOutput>,
): ReactElement => {
  const { form, children } = props
  const renderedChildren = typeof children === 'function' ? children(form) : children

  return (
    <FFormContext.Provider value={form}>
      <FormProvider {...form.rhf}>{renderedChildren}</FormProvider>
    </FFormContext.Provider>
  )
}

const FFormProviderWithSettings = <
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>(
  props: FFormProviderWithSettings<TFieldValues, TTransformedValues, TSubmitOutput>,
): ReactElement => {
  const { children, ...useFFormProps } = props
  const form = useFForm(useFFormProps)
  return <FFormProviderWithInstance form={form}>{children}</FFormProviderWithInstance>
}

export const FFormProvider = <
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>(
  props: FFormProviderProps<TFieldValues, TTransformedValues, TSubmitOutput>,
): ReactElement => {
  if ('form' in props && !!props.form) {
    return <FFormProviderWithInstance {...props} />
  }
  return <FFormProviderWithSettings {...props} />
}

export type FFormBaseProps<
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = Omit<FLayoutProps, 'children' | 'onSubmit'> & {
  children?: ReactNode | ((form: UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput>) => ReactNode)
}

export type FFormWithInstance<
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = FFormBaseProps<TFieldValues, TTransformedValues, TSubmitOutput> & {
  form: UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput>
}
export type FFormWithSettings<
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = FFormBaseProps<TFieldValues, TTransformedValues, TSubmitOutput> &
  UseFFormProps<TFieldValues, TTransformedValues, TSubmitOutput> & {
    form?: never
  }
export type FFormProps<
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> =
  | FFormWithInstance<TFieldValues, TTransformedValues, TSubmitOutput>
  | FFormWithSettings<TFieldValues, TTransformedValues, TSubmitOutput>

const FFormWithInstance = <
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>(
  props: FFormWithInstance<TFieldValues, TTransformedValues, TSubmitOutput>,
): ReactElement => {
  const { form, children, as = 'form', asChild, formProps, ...layoutProps } = props
  const renderedChildren = typeof children === 'function' ? children(form) : children
  // Apply the form-level id to the underlying <form> element; user-supplied
  // `formProps.id` wins if explicitly set.
  const mergedFormProps = form.id ? { id: form.id, ...formProps } : formProps
  return (
    <FFormProvider form={form}>
      <FLayout {...layoutProps} formProps={mergedFormProps} as={as} asChild={asChild} onSubmit={form.handleSubmit}>
        {renderedChildren}
      </FLayout>
    </FFormProvider>
  )
}

const FFormWithSettings = <
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>(
  props: FFormWithSettings<TFieldValues, TTransformedValues, TSubmitOutput>,
): ReactElement => {
  const { children, className, formProps, size, spacing, as = 'form', asChild, ...useFFormProps } = props
  const form = useFForm(useFFormProps)
  return (
    <FFormWithInstance
      form={form}
      className={className}
      formProps={formProps}
      size={size}
      spacing={spacing}
      as={as}
      asChild={asChild}
    >
      {children}
    </FFormWithInstance>
  )
}

/**
 * Build every form with `FForm` + the `F*` field components + a Zod `schema` + an `onSubmit` — never raw `<input>`,
 * per-field react-hook-form `rules`, or a button `onClick` that calls a mutation. The schema validates and types the
 * submit payload; `onSubmit` receives the parsed input and the form auto-handles disabled/dirty state, errors, toasts.
 *
 * @tags rule, form
 * @related FInput, FSelect
 */
export const FForm = <
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>(
  props: FFormProps<TFieldValues, TTransformedValues, TSubmitOutput>,
): ReactElement => {
  if ('form' in props && !!props.form) {
    return <FFormWithInstance {...props} />
  }
  return <FFormWithSettings {...props} />
}
