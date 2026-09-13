import { XInput } from '@/components/ui/input-group'
import type { WithFFieldControlledProps, WithFFieldUncontrolledProps } from '@/modules/form/core/field'
import {
  FFieldControlled,
  FFieldUncontrolled,
  splitFFieldControlledProps,
  splitFFieldUncontrolledProps,
} from '@/modules/form/core/field'
import { type FieldPath, type FieldValues } from 'react-hook-form'

/**
 * Form-bound text input — wires XInput into FForm (react-hook-form).
 *
 * @example
 *   ;<FInput name="email" label="Email" />
 *
 * @example
 *   ;<FInput name="password" label="Password" type="password" />
 *
 * @tags form, fields
 */
export function FInput<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>(
  props: WithFFieldUncontrolledProps<
    React.ComponentProps<typeof XInput>,
    TFieldValues,
    TName,
    TTransformedValues,
    TSubmitOutput
  > & { inputProps?: React.ComponentProps<typeof XInput> },
) {
  const {
    uncontrolledProps,
    rest: { inputProps, ...restInputProps },
  } = splitFFieldUncontrolledProps(props)
  return (
    <FFieldUncontrolled
      {...uncontrolledProps}
      render={({ id, invalid, disabled, initialValue, register }) => {
        return (
          <XInput
            {...restInputProps}
            {...inputProps}
            {...register()}
            defaultValue={initialValue}
            id={id}
            aria-invalid={invalid}
            disabled={disabled}
          />
        )
      }}
    />
  )
}

/**
 * Example of a controlled binding. Prefer `FInput` (uncontrolled via `register`) for plain text-like inputs — it
 * doesn't subscribe to the field value and therefore doesn't re-render on every keystroke. Use this controlled variant
 * only when you actually need to read / transform the value on every change (e.g. masked inputs).
 *
 * @example
 *   ;<FInputControlled name="phone" label="Phone" />
 *
 * @tags form, fields
 */
export function FInputControlled<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>(
  props: WithFFieldControlledProps<
    React.ComponentProps<typeof XInput>,
    TFieldValues,
    TName,
    TTransformedValues,
    TSubmitOutput
  > & { inputProps?: React.ComponentProps<typeof XInput> },
) {
  const {
    controlledProps,
    rest: { inputProps, ...restInputProps },
  } = splitFFieldControlledProps(props)
  return (
    <FFieldControlled
      {...controlledProps}
      render={({ id, invalid, disabled, field }) => {
        const { ref: inputRef, ...fieldProps } = field
        return (
          <XInput
            {...restInputProps}
            {...inputProps}
            {...fieldProps}
            value={fieldProps.value ?? ''}
            ref={inputRef}
            id={id}
            aria-invalid={invalid}
            disabled={disabled}
          />
        )
      }}
    />
  )
}
