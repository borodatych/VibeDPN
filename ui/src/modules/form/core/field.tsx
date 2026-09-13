import {
  Field,
  FieldContent,
  FieldDescription,
  FieldError,
  FieldLabel,
  isErrorsTruthy,
  type FieldErrorErrors,
} from '@/components/ui/field'
import { useFFormContext } from '@/modules/form/core/context'
import type { ReactNode } from 'react'
import { useCallback, useMemo, useState } from 'react'
import type {
  ChangeHandler,
  ControllerFieldState,
  RegisterOptions,
  UseFormRegisterReturn,
  UseFormStateReturn,
} from 'react-hook-form'
import { useFormState, type FieldPath, type FieldPathValue, type FieldValues } from 'react-hook-form'
import type { UseFControllerProps, UseFControllerReturn } from './controller'
import { FController, useFController } from './controller'
import type { UseFFormReturn } from './hook'

// ui

export type XFieldProps = {
  label?: ReactNode
  description?: ReactNode
  disabled?: boolean
  htmlFor?: string
  errors?: FieldErrorErrors
  invalid?: boolean
  children?: ReactNode
}
export const XField = ({ label, description, children, disabled, errors, invalid, htmlFor }: XFieldProps) => {
  return (
    <Field data-invalid={invalid} data-disabled={disabled}>
      <FieldContent>
        {!!label && <FieldLabel htmlFor={htmlFor}>{label}</FieldLabel>}
        {children}
        {!!description && <FieldDescription>{description}</FieldDescription>}
        <FieldError errors={errors} />
      </FieldContent>
    </Field>
  )
}

// calculated

export type FFieldCalculatedProps = {
  disabled?: boolean
  errors: FieldErrorErrors
  invalid: boolean
  id: string
}
export const getFFieldCalculatedProps = <
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>({
  form,
  fieldState,
  formState,
  disabled: disabledProvided,
  errors: errorsProvided,
  invalid: invalidProvided,
  id: idProvided,
  name: nameProvided,
}: {
  name: TName
  fieldState: ControllerFieldState
  formState: UseFormStateReturn<TFieldValues>
  form: UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput>
  disabled?: boolean
  errors?: FieldErrorErrors
  invalid?: boolean
  id?: string
}): FFieldCalculatedProps => {
  // NOTE: reading `isSubmitting` from the locally-subscribed `formState` (not from
  // `form.formState`) so that this component re-renders when submission state flips.
  // `form.formState` is the proxy from `useForm` and only triggers re-renders in the
  // component that called `useForm`, not in descendants reading via context.
  const disabled = disabledProvided || (form.settings.fieldDisabledOnFormSubmitting && formState.isSubmitting)
  const errors = errorsProvided || fieldState.error
  const invalid = invalidProvided || fieldState.invalid || isErrorsTruthy(errors)
  const id = idProvided || (form.id ? `${form.id}-${nameProvided}` : nameProvided)
  return {
    disabled,
    errors,
    invalid,
    id,
  }
}

// controlled

export type UseFFieldControlledProps<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = UseFControllerProps<TFieldValues, TName, TTransformedValues, TSubmitOutput> & {
  errors?: FieldErrorErrors
  invalid?: boolean
  disabled?: boolean
}

export type UseFFieldControlledReturn<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = UseFControllerReturn<TFieldValues, TName, TTransformedValues, TSubmitOutput> & FFieldCalculatedProps

export const useFFieldControlled = <
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>(
  props: UseFFieldControlledProps<TFieldValues, TName, TTransformedValues, TSubmitOutput>,
): UseFFieldControlledReturn<TFieldValues, TName, TTransformedValues, TSubmitOutput> => {
  // Strip UI-only field props (`disabled`/`errors`/`invalid`) before delegating to the
  // RHF controller. Especially important for `disabled`: see note in `FControllerProps`.
  const { disabled: disabledProvided, errors: errorsProvided, invalid: invalidProvided, ...controllerProps } = props
  const controller = useFController<TFieldValues, TName, TTransformedValues, TSubmitOutput>(controllerProps)
  const { form, fieldState, formState } = controller
  const { disabled, errors, invalid } = getFFieldCalculatedProps({
    form,
    fieldState,
    formState,
    disabled: disabledProvided,
    errors: errorsProvided,
    invalid: invalidProvided,
    id: props.id,
    name: props.name,
  })
  return useMemo(
    () => ({
      ...controller,
      disabled,
      errors,
      invalid,
    }),
    [controller, disabled, errors, invalid],
  )
}

export type FFieldControlledProps<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = {
  render: (
    props: FFieldControlledRenderProps<TFieldValues, TName, TTransformedValues, TSubmitOutput>,
  ) => React.ReactElement
  bare?: boolean
} & Omit<XFieldProps, 'children'> &
  UseFFieldControlledProps<TFieldValues, TName, TTransformedValues, TSubmitOutput>

export type FFieldControlledRenderProps<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = UseFFieldControlledReturn<TFieldValues, TName, TTransformedValues, TSubmitOutput>

export const FFieldControlled = <
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>(
  props: FFieldControlledProps<TFieldValues, TName, TTransformedValues, TSubmitOutput>,
): React.ReactElement => {
  const {
    render,
    id: idProvided,
    label,
    disabled: disabledProvided,
    description,
    errors: errorsProvided,
    invalid: invalidProvided,
    form: formProvided,
    name,
    bare,
    ...controllerProps
  } = props

  return (
    <FController
      {...controllerProps}
      form={formProvided}
      id={idProvided}
      name={name}
      render={({ field, fieldState, formState, form, id }) => {
        const { disabled, errors, invalid } = getFFieldCalculatedProps({
          form,
          fieldState,
          formState,
          disabled: disabledProvided,
          errors: errorsProvided,
          invalid: invalidProvided,
          id,
          name,
        })
        const rendered = render({
          field,
          fieldState,
          formState,
          id,
          errors,
          invalid,
          disabled,
          form,
        })
        if (bare) {
          return rendered
        }
        return (
          <XField
            description={description}
            label={label}
            htmlFor={id}
            errors={errors}
            invalid={invalid}
            disabled={disabled}
          >
            {rendered}
          </XField>
        )
      }}
    />
  )
}
FFieldControlled.displayName = 'FFieldControlled'

export type WithFFieldControlledProps<
  TProps = object,
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = Omit<FFieldControlledProps<TFieldValues, TName, TTransformedValues, TSubmitOutput>, 'render'> &
  Omit<TProps, keyof FFieldControlledProps<TFieldValues, TName, TTransformedValues, TSubmitOutput>>
export const splitFFieldControlledProps = <TProps extends Record<string, any>>(props: TProps) => {
  const {
    name,
    form,
    label,
    description,
    id,
    disabled,
    bare,
    errors,
    invalid,
    htmlFor,
    defaultValue,
    rules,
    shouldUnregister,
    ...rest
  } = props
  const controlledProps = {
    name,
    form,
    label,
    description,
    id,
    disabled,
    bare,
    errors,
    invalid,
    htmlFor,
    defaultValue,
    rules,
    shouldUnregister,
  }
  return { controlledProps, rest }
}

// uncontrolled

type RegisterOptionsOverrides<TFieldValues extends FieldValues, TName extends FieldPath<TFieldValues>> = Partial<
  Omit<RegisterOptions<TFieldValues, TName>, 'disabled'>
>

export type UseFFieldUncontrolledProps<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = {
  name: TName
  id?: string
  form?: UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput>
  errors?: FieldErrorErrors
  invalid?: boolean
  disabled?: boolean
  setValueAs?: (value: any) => any
  onChange?: ChangeHandler
  onBlur?: ChangeHandler
} & (
  | {
      valueAsNumber?: false
      valueAsDate?: true
    }
  | {
      valueAsNumber?: true
      valueAsDate?: false
    }
)

export type UseFFieldUncontrolledReturn<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = {
  form: UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput>
  name: TName
  id: string
  errors: FieldErrorErrors
  invalid: boolean
  disabled?: boolean
  initialValue: FieldPathValue<TFieldValues, TName> | undefined
  fieldState: ControllerFieldState
  formState: UseFormStateReturn<TFieldValues>
  register: (options?: RegisterOptionsOverrides<TFieldValues, TName>) => UseFormRegisterReturn<TName>
}

export const useFFieldUncontrolled = <
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>({
  name,
  id: idProvided,
  form: formProvided,
  errors: errorsProvided,
  invalid: invalidProvided,
  disabled: disabledProvided,
  setValueAs,
  valueAsNumber,
  valueAsDate,
  onChange,
  onBlur,
}: UseFFieldUncontrolledProps<TFieldValues, TName, TTransformedValues, TSubmitOutput>): UseFFieldUncontrolledReturn<
  TFieldValues,
  TName,
  TTransformedValues,
  TSubmitOutput
> => {
  const form = useFFormContext<TFieldValues, TTransformedValues, TSubmitOutput>({ form: formProvided })
  // `exact: true` scopes field-level subscriptions (errors/touched/dirty) to this `name`,
  // but form-level state like `isSubmitting` is still tracked via proxy access below.
  const formState = useFormState({ control: form.control, name, exact: true })
  // `form.getFieldState` is not memoized in RHF — it returns a fresh object each call.
  // Memoize against the stable `formState` reference (RHF mutates it only when this
  // field's state actually changed) so downstream deps stay reference-stable.
  const fieldState = useMemo(() => form.getFieldState(name, formState), [form, name, formState])
  const { disabled, errors, invalid, id } = getFFieldCalculatedProps({
    form,
    fieldState,
    formState,
    disabled: disabledProvided,
    errors: errorsProvided,
    invalid: invalidProvided,
    id: idProvided,
    name,
  })
  const register = useCallback(
    (options?: RegisterOptionsOverrides<TFieldValues, TName>) =>
      form.register(name, {
        valueAsDate: valueAsDate as never,
        valueAsNumber: valueAsNumber as never,
        setValueAs,
        onChange,
        onBlur,
        ...(options as object),
      }),
    [form, name, valueAsDate, valueAsNumber, setValueAs, onChange, onBlur],
  )
  const [initialValue] = useState(() => form.getValues(name))
  return useMemo(
    () => ({
      form,
      name,
      id,
      disabled,
      errors,
      invalid,
      initialValue,
      fieldState,
      formState,
      register,
    }),
    [form, name, id, disabled, errors, invalid, initialValue, fieldState, formState, register],
  )
}

export type FFieldUncontrolledProps<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = {
  render: (
    props: FFieldUncontrolledRenderProps<TFieldValues, TName, TTransformedValues, TSubmitOutput>,
  ) => React.ReactElement
  bare?: boolean
} & Omit<XFieldProps, 'children'> &
  UseFFieldUncontrolledProps<TFieldValues, TName, TTransformedValues, TSubmitOutput>

export type FFieldUncontrolledRenderProps<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = UseFFieldUncontrolledReturn<TFieldValues, TName, TTransformedValues, TSubmitOutput>

export const FFieldUncontrolled = <
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>({
  bare,
  label,
  description,
  ...props
}: FFieldUncontrolledProps<TFieldValues, TName, TTransformedValues, TSubmitOutput>): React.ReactElement => {
  const ffieldUncontrolled = useFFieldUncontrolled<TFieldValues, TName, TTransformedValues, TSubmitOutput>(props)
  const rendered = props.render(ffieldUncontrolled)
  if (bare) {
    return rendered
  }
  const { id, errors, invalid, disabled } = ffieldUncontrolled
  return (
    <XField description={description} label={label} htmlFor={id} errors={errors} invalid={invalid} disabled={disabled}>
      {rendered}
    </XField>
  )
}
FFieldUncontrolled.displayName = 'FFieldUncontrolled'

export type WithFFieldUncontrolledProps<
  TProps = object,
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = Omit<FFieldUncontrolledProps<TFieldValues, TName, TTransformedValues, TSubmitOutput>, 'render'> &
  Omit<TProps, keyof FFieldUncontrolledProps<TFieldValues, TName, TTransformedValues, TSubmitOutput>>
export const splitFFieldUncontrolledProps = <TProps extends Record<string, any>>(props: TProps) => {
  const {
    name,
    form,
    label,
    description,
    id,
    disabled,
    bare,
    onChange,
    onBlur,
    errors,
    invalid,
    htmlFor,
    setValueAs,
    valueAsNumber,
    valueAsDate,
    ...rest
  } = props
  const uncontrolledProps = {
    name,
    form,
    label,
    description,
    id,
    disabled,
    bare,
    onChange,
    onBlur,
    errors,
    invalid,
    htmlFor,
    setValueAs,
    valueAsNumber,
    valueAsDate,
  }
  return { uncontrolledProps, rest }
}
