import * as React from 'react'
import { Checkbox as CheckboxPrimitive } from 'radix-ui'

import {
  Field,
  FieldContent,
  FieldDescription,
  FieldError,
  FieldLabel,
  isErrorsTruthy,
  type FieldErrorErrors,
} from '@/components/ui/field'
import { cn } from '@/utils/index'
import type { XOptionValue, XOptionValueType } from '@/utils/option-value'
import { stringifyXOptionPrimitiveValue } from '@/utils/option-value'
import { CheckIcon } from 'lucide-react'

function Checkbox({ className, ...props }: React.ComponentProps<typeof CheckboxPrimitive.Root>) {
  return (
    <CheckboxPrimitive.Root
      data-slot="checkbox"
      className={cn(
        'peer relative flex size-4 shrink-0 items-center justify-center rounded-[4px] border border-input shadow-xs transition-shadow outline-none group-has-disabled/field:opacity-50 after:absolute after:-inset-x-3 after:-inset-y-2 focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 aria-invalid:aria-checked:border-primary dark:bg-input/30 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40 data-checked:border-primary data-checked:bg-primary data-checked:text-primary-foreground dark:data-checked:bg-primary',
        className,
      )}
      {...props}
    >
      <CheckboxPrimitive.Indicator
        data-slot="checkbox-indicator"
        className="grid place-content-center text-current transition-none [&>svg]:size-3.5"
      >
        <CheckIcon />
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  )
}

export { Checkbox }

export type XCheckboxGroupOption = {
  value: XOptionValue
  valueType?: XOptionValueType
  label: React.ReactNode
  checked?: boolean
  disabled?: boolean
  description?: React.ReactNode
  errors?: FieldErrorErrors
  invalid?: boolean
  fieldProps?: React.ComponentProps<typeof Field>
  checkboxProps?: Omit<React.ComponentProps<typeof Checkbox>, 'checked' | 'disabled' | 'value'>
  labelProps?: Omit<React.ComponentProps<typeof FieldLabel>, 'children' | 'htmlFor'>
  contentProps?: React.ComponentProps<typeof FieldContent>
}

export type XCheckboxGroupProps = Omit<React.ComponentProps<'div'>, 'children' | 'onChange'> & {
  options: readonly XCheckboxGroupOption[]
  valueType?: XOptionValueType
  disabled?: boolean
  checkboxProps?: Omit<React.ComponentProps<typeof Checkbox>, 'checked' | 'disabled' | 'value'>
  labelProps?: Omit<React.ComponentProps<typeof FieldLabel>, 'children' | 'htmlFor'>
  contentProps?: React.ComponentProps<typeof FieldContent>
  fieldProps?: React.ComponentProps<typeof Field>
  onOptionCheckedChange?: (option: XCheckboxGroupOption, checked: boolean) => void
}

export function XCheckboxGroup({
  options,
  valueType,
  disabled,
  checkboxProps,
  labelProps,
  contentProps,
  fieldProps,
  onOptionCheckedChange,
  className,
  id,
  ...props
}: XCheckboxGroupProps) {
  const fallbackId = React.useId()
  const baseId = id ?? fallbackId

  return (
    <div data-slot="checkbox-group" id={id} className={cn('flex flex-col gap-3', className)} {...props}>
      {options.map((option, index) => {
        const optionKey = stringifyXOptionPrimitiveValue(option.value, option.valueType ?? valueType)
        const optionId = option.checkboxProps?.id ?? `${baseId}-${index}`
        const optionDisabled = disabled || option.disabled
        const optionInvalid = option.invalid || isErrorsTruthy(option.errors)

        return (
          <Field
            key={optionKey}
            orientation="horizontal"
            data-invalid={optionInvalid}
            data-disabled={optionDisabled}
            {...fieldProps}
            {...option.fieldProps}
          >
            <Checkbox
              {...checkboxProps}
              {...option.checkboxProps}
              id={optionId}
              value={optionKey}
              checked={option.checked}
              disabled={optionDisabled}
              aria-invalid={optionInvalid}
              onCheckedChange={(nextChecked) => {
                checkboxProps?.onCheckedChange?.(nextChecked)
                option.checkboxProps?.onCheckedChange?.(nextChecked)
                onOptionCheckedChange?.(option, nextChecked === true)
              }}
            />
            <FieldContent {...contentProps} {...option.contentProps}>
              <FieldLabel {...labelProps} {...option.labelProps} htmlFor={optionId}>
                {option.label}
              </FieldLabel>
              {!!option.description && <FieldDescription>{option.description}</FieldDescription>}
              <FieldError errors={option.errors} />
            </FieldContent>
          </Field>
        )
      })}
    </div>
  )
}
