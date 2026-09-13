import * as React from 'react'
import { RadioGroup as RadioGroupPrimitive } from 'radix-ui'

import { Label } from '@/components/ui/label'
import {
  getXOptionPrimitiveValue,
  parseXOptionPrimitiveValue,
  stringifyXOptionPrimitiveValue,
  type XOptionValue,
  type XOptionValueType,
} from '@/utils/option-value'
import { cn } from '@/utils/index'

function RadioGroup({ className, ...props }: React.ComponentProps<typeof RadioGroupPrimitive.Root>) {
  return <RadioGroupPrimitive.Root data-slot="radio-group" className={cn('grid w-full gap-3', className)} {...props} />
}

function RadioGroupItem({ className, ...props }: React.ComponentProps<typeof RadioGroupPrimitive.Item>) {
  return (
    <RadioGroupPrimitive.Item
      data-slot="radio-group-item"
      className={cn(
        'group/radio-group-item peer relative flex aspect-square size-4 shrink-0 rounded-full border border-input outline-none after:absolute after:-inset-x-3 after:-inset-y-2 focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 aria-invalid:aria-checked:border-primary dark:bg-input/30 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40 data-checked:border-primary data-checked:bg-primary data-checked:text-primary-foreground dark:data-checked:bg-primary',
        className,
      )}
      {...props}
    >
      <RadioGroupPrimitive.Indicator
        data-slot="radio-group-indicator"
        className="flex size-4 items-center justify-center"
      >
        <span className="absolute top-1/2 left-1/2 size-2 -translate-1/2 rounded-full bg-primary-foreground" />
      </RadioGroupPrimitive.Indicator>
    </RadioGroupPrimitive.Item>
  )
}

export { RadioGroup, RadioGroupItem }

export type XRadioGroupValue = XOptionValue
export type XRadioGroupValueType = XOptionValueType

export type XRadioGroupOption = {
  value: XRadioGroupValue
  valueType?: XRadioGroupValueType
  label: React.ReactNode
  disabled?: boolean
  wrapperProps?: React.ComponentProps<'div'>
  itemProps?: Omit<React.ComponentProps<typeof RadioGroupItem>, 'disabled' | 'value'>
  labelProps?: Omit<React.ComponentProps<typeof Label>, 'children' | 'htmlFor'>
}

export type XRadioGroupProps = Omit<
  React.ComponentProps<typeof RadioGroup>,
  'children' | 'value' | 'defaultValue' | 'onValueChange'
> & {
  options: readonly XRadioGroupOption[]
  value?: XRadioGroupValue
  defaultValue?: XRadioGroupValue
  valueType?: XRadioGroupValueType
  onValueChange?: (value: XRadioGroupValue) => void
  optionWrapperProps?: React.ComponentProps<'div'>
  itemProps?: Omit<React.ComponentProps<typeof RadioGroupItem>, 'disabled' | 'value'>
  labelProps?: Omit<React.ComponentProps<typeof Label>, 'children' | 'htmlFor'>
}

export function XRadioGroup({
  options,
  optionWrapperProps,
  itemProps,
  labelProps,
  id,
  value,
  defaultValue,
  valueType,
  onValueChange,
  ...props
}: XRadioGroupProps) {
  const fallbackId = React.useId()
  const baseId = id ?? fallbackId

  return (
    <RadioGroup
      id={id}
      {...props}
      value={getXOptionPrimitiveValue(options, value, valueType)}
      defaultValue={getXOptionPrimitiveValue(options, defaultValue, valueType)}
      onValueChange={(nextValue) => {
        onValueChange?.(parseXOptionPrimitiveValue(nextValue, options, valueType))
      }}
    >
      {options.map((option, index) => {
        const itemValue = stringifyXOptionPrimitiveValue(option.value, option.valueType ?? valueType)
        const itemId = option.itemProps?.id ?? `${baseId}-${index}`

        return (
          <div
            key={itemValue}
            {...optionWrapperProps}
            {...option.wrapperProps}
            className={cn('flex items-center gap-2', optionWrapperProps?.className, option.wrapperProps?.className)}
          >
            <RadioGroupItem
              {...itemProps}
              {...option.itemProps}
              id={itemId}
              value={itemValue}
              disabled={option.disabled}
            />
            <Label {...labelProps} {...option.labelProps} htmlFor={itemId}>
              {option.label}
            </Label>
          </div>
        )
      })}
    </RadioGroup>
  )
}
