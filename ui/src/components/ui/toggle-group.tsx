'use client'

import * as React from 'react'
import { type VariantProps } from 'class-variance-authority'
import { ToggleGroup as ToggleGroupPrimitive } from 'radix-ui'

import { cn } from '@/utils'
import { toggleVariants } from '@/components/ui/toggle'
import {
  getXOptionPrimitiveValue,
  parseXOptionPrimitiveValue,
  stringifyXOptionPrimitiveValue,
  type XOptionValue,
  type XOptionValueType,
} from '@/utils/option-value'

const ToggleGroupContext = React.createContext<
  VariantProps<typeof toggleVariants> & {
    spacing?: number
    orientation?: 'horizontal' | 'vertical'
  }
>({
  size: 'default',
  variant: 'default',
  spacing: 2,
  orientation: 'horizontal',
})

function ToggleGroup({
  className,
  variant,
  size,
  spacing = 2,
  orientation = 'horizontal',
  children,
  ...props
}: React.ComponentProps<typeof ToggleGroupPrimitive.Root> &
  VariantProps<typeof toggleVariants> & {
    spacing?: number
    orientation?: 'horizontal' | 'vertical'
  }) {
  return (
    <ToggleGroupPrimitive.Root
      data-slot="toggle-group"
      data-variant={variant}
      data-size={size}
      data-spacing={spacing}
      data-orientation={orientation}
      style={{ '--gap': spacing } as React.CSSProperties}
      className={cn(
        'group/toggle-group flex w-fit flex-row items-center gap-[--spacing(var(--gap))] rounded-md data-[spacing=0]:data-[variant=outline]:shadow-xs data-vertical:flex-col data-vertical:items-stretch',
        className,
      )}
      {...props}
    >
      <ToggleGroupContext.Provider value={{ variant, size, spacing, orientation }}>
        {children}
      </ToggleGroupContext.Provider>
    </ToggleGroupPrimitive.Root>
  )
}

function ToggleGroupItem({
  className,
  children,
  variant = 'default',
  size = 'default',
  ...props
}: React.ComponentProps<typeof ToggleGroupPrimitive.Item> & VariantProps<typeof toggleVariants>) {
  const context = React.useContext(ToggleGroupContext)

  return (
    <ToggleGroupPrimitive.Item
      data-slot="toggle-group-item"
      data-variant={context.variant || variant}
      data-size={context.size || size}
      data-spacing={context.spacing}
      className={cn(
        'shrink-0 group-data-[spacing=0]/toggle-group:rounded-none group-data-[spacing=0]/toggle-group:px-2 group-data-[spacing=0]/toggle-group:shadow-none focus:z-10 focus-visible:z-10 group-data-[spacing=0]/toggle-group:has-data-[icon=inline-end]:pr-1.5 group-data-[spacing=0]/toggle-group:has-data-[icon=inline-start]:pl-1.5 group-data-horizontal/toggle-group:data-[spacing=0]:first:rounded-l-md group-data-vertical/toggle-group:data-[spacing=0]:first:rounded-t-md group-data-horizontal/toggle-group:data-[spacing=0]:last:rounded-r-md group-data-vertical/toggle-group:data-[spacing=0]:last:rounded-b-md data-[state=on]:bg-muted group-data-horizontal/toggle-group:data-[spacing=0]:data-[variant=outline]:border-l-0 group-data-vertical/toggle-group:data-[spacing=0]:data-[variant=outline]:border-t-0 group-data-horizontal/toggle-group:data-[spacing=0]:data-[variant=outline]:first:border-l group-data-vertical/toggle-group:data-[spacing=0]:data-[variant=outline]:first:border-t',
        toggleVariants({
          variant: context.variant || variant,
          size: context.size || size,
        }),
        className,
      )}
      {...props}
    >
      {children}
    </ToggleGroupPrimitive.Item>
  )
}

export { ToggleGroup, ToggleGroupItem }

export type XToggleGroupValue = XOptionValue
export type XToggleGroupValueType = XOptionValueType

export type XToggleGroupOption = {
  value: XToggleGroupValue
  valueType?: XToggleGroupValueType
  label: React.ReactNode
  disabled?: boolean
  itemProps?: Omit<React.ComponentProps<typeof ToggleGroupItem>, 'children' | 'disabled' | 'value'>
}

export type XToggleGroupProps = Omit<
  React.ComponentProps<typeof ToggleGroup>,
  'children' | 'type' | 'value' | 'defaultValue' | 'onValueChange'
> & {
  options: readonly XToggleGroupOption[]
  value?: XToggleGroupValue
  defaultValue?: XToggleGroupValue
  valueType?: XToggleGroupValueType
  onValueChange?: (value: XToggleGroupValue | undefined) => void
  itemProps?: Omit<React.ComponentProps<typeof ToggleGroupItem>, 'children' | 'disabled' | 'value'>
  allowEmpty?: boolean
}

export function XToggleGroup({
  options,
  value,
  defaultValue,
  valueType,
  onValueChange,
  itemProps,
  allowEmpty,
  ...props
}: XToggleGroupProps) {
  return (
    <ToggleGroup
      {...props}
      type="single"
      value={getXOptionPrimitiveValue(options, value, valueType)}
      defaultValue={getXOptionPrimitiveValue(options, defaultValue, valueType)}
      onValueChange={(nextValue) => {
        if (nextValue === '') {
          if (allowEmpty) {
            onValueChange?.(undefined)
          }
          return
        }

        onValueChange?.(parseXOptionPrimitiveValue(nextValue, options, valueType))
      }}
    >
      {options.map((option) => {
        const optionValue = stringifyXOptionPrimitiveValue(option.value, option.valueType ?? valueType)

        return (
          <ToggleGroupItem
            key={optionValue}
            {...itemProps}
            {...option.itemProps}
            value={optionValue}
            disabled={option.disabled}
          >
            {option.label}
          </ToggleGroupItem>
        )
      })}
    </ToggleGroup>
  )
}
