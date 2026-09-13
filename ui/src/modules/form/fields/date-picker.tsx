import { XDatePicker } from '@/components/ui/date-picker'
import type { WithFFieldControlledProps } from '@/modules/form/core/field'
import { FFieldControlled, splitFFieldControlledProps } from '@/modules/form/core/field'
import { type FieldPath, type FieldValues } from 'react-hook-form'

/**
 * Form-bound date picker for FForm.
 *
 * @example
 *   ;<FDatePicker name="startsAt" label="Start date" />
 *
 * @example
 *   ;<FDatePicker name="birthday" label="Birthday" placeholder="June 01, 2025" />
 *
 * @tags form, fields
 */
export function FDatePicker<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>(
  props: WithFFieldControlledProps<
    React.ComponentProps<typeof XDatePicker>,
    TFieldValues,
    TName,
    TTransformedValues,
    TSubmitOutput
  >,
) {
  const {
    controlledProps,
    rest: { onBlur, onValueChange, ...datePickerProps },
  } = splitFFieldControlledProps(props)

  return (
    <FFieldControlled
      {...controlledProps}
      render={({ id, invalid, disabled, field }) => {
        const { ref: inputRef, value, onChange, onBlur: fieldOnBlur, name } = field

        return (
          <XDatePicker
            {...datePickerProps}
            ref={inputRef}
            id={id}
            name={name}
            value={value instanceof Date ? value : undefined}
            onValueChange={(nextDate) => {
              onChange(nextDate)
              onValueChange?.(nextDate)
            }}
            onBlur={(event) => {
              onBlur?.(event)
              fieldOnBlur()
            }}
            aria-invalid={invalid}
            disabled={disabled}
          />
        )
      }}
    />
  )
}
