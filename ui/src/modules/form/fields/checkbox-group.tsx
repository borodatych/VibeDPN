import { XCheckboxGroup, type XCheckboxGroupOption, type XCheckboxGroupProps } from '@/components/ui/checkbox'
import { XField, type XFieldProps } from '@/modules/form/core/field'
import type { UseFFormReturn } from '@/modules/form/core/hook'
import type { XOptionValue } from '@/utils/option-value'
import { stringifyXOptionPrimitiveValue } from '@/utils/option-value'
import type { FieldPath, FieldValues } from 'react-hook-form'
import type { WithFFieldControlledProps } from '@/modules/form/core/field'
import { FFieldControlled, splitFFieldControlledProps } from '@/modules/form/core/field'

const isSameCheckboxValue = (left: XOptionValue, right: XOptionValue, valueType: XCheckboxGroupProps['valueType']) =>
  stringifyXOptionPrimitiveValue(left, valueType) === stringifyXOptionPrimitiveValue(right, valueType)

const hasCheckboxValue = (
  values: readonly XOptionValue[],
  value: XOptionValue,
  valueType: XCheckboxGroupProps['valueType'],
) => values.some((currentValue) => isSameCheckboxValue(currentValue, value, valueType))

/**
 * Form-bound checkbox group binding to an array of selected values.
 *
 * @example
 *   ;<FCheckboxGroupArray
 *     name="roles"
 *     label="Roles"
 *     options={[
 *       { value: 'admin', label: 'Admin' },
 *       { value: 'member', label: 'Member' },
 *     ]}
 *   />
 *
 * @example
 *   ;<FCheckboxGroupArray
 *     name="statusIds"
 *     label="Statuses"
 *     valueType="number"
 *     options={[
 *       { value: 1, label: 'Active' },
 *       { value: 0, label: 'Inactive' },
 *     ]}
 *   />
 *
 * @tags form, fields
 */
export function FCheckboxGroupArray<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>(props: WithFFieldControlledProps<XCheckboxGroupProps, TFieldValues, TName, TTransformedValues, TSubmitOutput>) {
  const {
    controlledProps,
    rest: { options, onOptionCheckedChange, valueType, ...checkboxGroupProps },
  } = splitFFieldControlledProps(props)

  return (
    <FFieldControlled
      {...controlledProps}
      render={({ id, invalid, disabled, field }) => {
        const { value, onChange, onBlur } = field
        const values = Array.isArray(value) ? (value as XOptionValue[]) : []

        return (
          <XCheckboxGroup
            {...checkboxGroupProps}
            id={id}
            valueType={valueType}
            disabled={disabled}
            aria-invalid={invalid}
            options={options.map((option) => ({
              ...option,
              checked: hasCheckboxValue(values, option.value, option.valueType ?? valueType),
            }))}
            onBlur={(event) => {
              checkboxGroupProps.onBlur?.(event)
              onBlur()
            }}
            onOptionCheckedChange={(option, checked) => {
              const nextValues = checked
                ? hasCheckboxValue(values, option.value, option.valueType ?? valueType)
                  ? values
                  : [...values, option.value]
                : values.filter(
                    (currentValue) => !isSameCheckboxValue(currentValue, option.value, option.valueType ?? valueType),
                  )

              onChange(nextValues)
              onOptionCheckedChange?.(option, checked)
            }}
          />
        )
      }}
    />
  )
}

export type FCheckboxGroupBooleanOption<TFieldValues extends FieldValues = FieldValues> = Omit<
  XCheckboxGroupOption,
  'value' | 'checked' | 'errors' | 'invalid'
> & {
  name: FieldPath<TFieldValues>
}

export type FCheckboxGroupBooleanProps<
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = Omit<XCheckboxGroupProps, 'options' | 'onOptionCheckedChange'> &
  Omit<XFieldProps, 'children' | 'errors' | 'htmlFor' | 'invalid'> & {
    options: readonly FCheckboxGroupBooleanOption<TFieldValues>[]
    form?: UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput>
    bare?: boolean
    onOptionCheckedChange?: (option: FCheckboxGroupBooleanOption<TFieldValues>, checked: boolean) => void
  }

/**
 * Form-bound checkbox group binding each option to its own boolean.
 *
 * @example
 *   ;<FCheckboxGroupBoolean
 *     label="Permissions"
 *     options={[
 *       { name: 'canCreate', label: 'Create records' },
 *       { name: 'canDelete', label: 'Delete records' },
 *     ]}
 *   />
 *
 * @example
 *   ;<FCheckboxGroupBoolean bare options={[{ name: 'acceptTerms', label: 'Accept terms' }]} />
 *
 * @tags form, fields
 */
export function FCheckboxGroupBoolean<
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>({
  options,
  form,
  label,
  description,
  disabled,
  bare,
  onOptionCheckedChange,
  ...checkboxGroupProps
}: FCheckboxGroupBooleanProps<TFieldValues, TTransformedValues, TSubmitOutput>) {
  const rendered = (
    <div data-slot="checkbox-group" className="flex flex-col gap-3">
      {options.map((option) => {
        const { name, ...checkboxOption } = option

        return (
          <FFieldControlled
            key={name}
            form={form}
            name={name}
            disabled={disabled}
            bare
            render={({ id, invalid, disabled: optionDisabled, errors, field }) => {
              const { value, onChange, onBlur } = field

              return (
                <XCheckboxGroup
                  {...checkboxGroupProps}
                  options={[
                    {
                      ...checkboxOption,
                      value: name,
                      checked: value === true,
                      disabled: optionDisabled || checkboxOption.disabled,
                      errors,
                      invalid,
                    },
                  ]}
                  onBlur={(event) => {
                    checkboxGroupProps.onBlur?.(event)
                    onBlur()
                  }}
                  onOptionCheckedChange={(_, checked) => {
                    onChange(checked)
                    onOptionCheckedChange?.(option, checked)
                  }}
                  id={id}
                />
              )
            }}
          />
        )
      })}
    </div>
  )

  if (bare) {
    return rendered
  }

  return (
    <XField label={label} description={description} disabled={disabled}>
      {rendered}
    </XField>
  )
}
