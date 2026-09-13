import { XSelect } from '@/components/ui/select'
import type { WithFFieldControlledProps } from '@/modules/form/core/field'
import { FFieldControlled, splitFFieldControlledProps } from '@/modules/form/core/field'
import { type FieldPath, type FieldValues } from 'react-hook-form'

/**
 * Form-bound single-select dropdown for FForm.
 *
 * @example
 *   ;<FSelect
 *     name="role"
 *     label="Role"
 *     options={[
 *       { value: 'admin', label: 'Admin' },
 *       { value: 'member', label: 'Member' },
 *     ]}
 *   />
 *
 * @example
 *   ;<FSelect
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
export function FSelect<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>(
  props: WithFFieldControlledProps<
    React.ComponentProps<typeof XSelect>,
    TFieldValues,
    TName,
    TTransformedValues,
    TSubmitOutput
  >,
) {
  const {
    controlledProps,
    rest: { triggerProps, onValueChange, ...selectProps },
  } = splitFFieldControlledProps(props)

  return (
    <FFieldControlled
      {...controlledProps}
      render={({ id, invalid, disabled, field }) => {
        const { ref: triggerRef, value, onChange, onBlur, name } = field

        return (
          <XSelect
            {...selectProps}
            name={name}
            value={value === undefined ? undefined : value}
            onValueChange={(nextValue) => {
              onChange(nextValue)
              onValueChange?.(nextValue)
            }}
            disabled={disabled}
            triggerProps={{
              ...triggerProps,
              id,
              ref: triggerRef,
              'aria-invalid': invalid,
              disabled,
              onBlur: (event) => {
                triggerProps?.onBlur?.(event)
                onBlur()
              },
            }}
          />
        )
      }}
    />
  )
}
