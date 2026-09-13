import { XRadioGroup } from '@/components/ui/radio-group'
import type { WithFFieldControlledProps } from '@/modules/form/core/field'
import { FFieldControlled, splitFFieldControlledProps } from '@/modules/form/core/field'
import { type FieldPath, type FieldValues } from 'react-hook-form'

/**
 * Form-bound radio group (one choice) for FForm.
 *
 * @example
 *   ;<FRadioGroup
 *     name="role"
 *     label="Role"
 *     options={[
 *       { value: 'admin', label: 'Admin' },
 *       { value: 'member', label: 'Member' },
 *     ]}
 *   />
 *
 * @example
 *   ;<FRadioGroup
 *     name="remember"
 *     label="Remember this device?"
 *     options={[
 *       { value: true, label: 'Yes' },
 *       { value: false, label: 'No' },
 *     ]}
 *   />
 *
 * @tags form, fields
 */
export function FRadioGroup<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>(
  props: WithFFieldControlledProps<
    React.ComponentProps<typeof XRadioGroup>,
    TFieldValues,
    TName,
    TTransformedValues,
    TSubmitOutput
  >,
) {
  const {
    controlledProps,
    rest: { onBlur, onValueChange, ...radioGroupProps },
  } = splitFFieldControlledProps(props)

  return (
    <FFieldControlled
      {...controlledProps}
      render={({ id, invalid, disabled, field }) => {
        const { ref: radioGroupRef, value, onChange, onBlur: fieldOnBlur, name } = field

        return (
          <XRadioGroup
            {...radioGroupProps}
            ref={radioGroupRef}
            id={id}
            name={name}
            value={value === undefined ? undefined : value}
            onValueChange={(nextValue) => {
              onChange(nextValue)
              onValueChange?.(nextValue)
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
