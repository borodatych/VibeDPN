import { XToggleGroup } from '@/components/ui/toggle-group'
import type { WithFFieldControlledProps } from '@/modules/form/core/field'
import { FFieldControlled, splitFFieldControlledProps } from '@/modules/form/core/field'
import { type FieldPath, type FieldValues } from 'react-hook-form'

/**
 * Form-bound toggle group for FForm.
 *
 * @example
 *   ;<FToggleGroup
 *     name="period"
 *     label="Period"
 *     options={[
 *       { value: 'month', label: 'Month' },
 *       { value: 'year', label: 'Year' },
 *     ]}
 *   />
 *
 * @example
 *   ;<FToggleGroup
 *     name="statusId"
 *     label="Status"
 *     valueType="number"
 *     options={[
 *       { value: 1, label: 'Active' },
 *       { value: 0, label: 'Inactive' },
 *     ]}
 *   />
 *
 * @tags form, fields
 */
export function FToggleGroup<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>(
  props: WithFFieldControlledProps<
    React.ComponentProps<typeof XToggleGroup>,
    TFieldValues,
    TName,
    TTransformedValues,
    TSubmitOutput
  >,
) {
  const {
    controlledProps,
    rest: { onBlur, onValueChange, ...toggleGroupProps },
  } = splitFFieldControlledProps(props)

  return (
    <FFieldControlled
      {...controlledProps}
      render={({ id, invalid, disabled, field }) => {
        const { ref: toggleGroupRef, value, onChange, onBlur: fieldOnBlur } = field

        return (
          <XToggleGroup
            {...toggleGroupProps}
            ref={toggleGroupRef}
            id={id}
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
