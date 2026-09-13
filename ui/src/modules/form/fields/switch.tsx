import { XSwitch } from '@/components/ui/switch'
import type { WithFFieldControlledProps } from '@/modules/form/core/field'
import { FFieldControlled, splitFFieldControlledProps } from '@/modules/form/core/field'
import { type FieldPath, type FieldValues } from 'react-hook-form'

type FSwitchProps = Omit<React.ComponentProps<typeof XSwitch>, 'label'> & {
  switchLabel?: React.ComponentProps<typeof XSwitch>['label']
}

/**
 * Form-bound on/off switch for FForm.
 *
 * @example
 *   ;<FSwitch name="enabled" label="Settings" switchLabel="Enable notifications" />
 *
 * @example
 *   ;<FSwitch name="newsletter" switchLabel="Send product updates" bare />
 *
 * @tags form, fields
 */
export function FSwitch<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>(props: WithFFieldControlledProps<FSwitchProps, TFieldValues, TName, TTransformedValues, TSubmitOutput>) {
  const {
    controlledProps,
    rest: { switchLabel, onBlur, onCheckedChange, ...switchProps },
  } = splitFFieldControlledProps(props)

  return (
    <FFieldControlled
      {...controlledProps}
      render={({ id, invalid, disabled, field }) => {
        const { ref: switchRef, value, onChange, onBlur: fieldOnBlur, name } = field

        return (
          <XSwitch
            {...switchProps}
            ref={switchRef}
            id={id}
            name={name}
            label={switchLabel}
            checked={!!value}
            onCheckedChange={(nextChecked) => {
              onChange(nextChecked)
              onCheckedChange?.(nextChecked)
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
