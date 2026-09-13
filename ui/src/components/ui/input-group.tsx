'use client'

import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/utils'
import type { DistributiveOmit } from '@/types'
import { Button } from '@/components/ui/button'
import { Icon, type IconType } from '@/components/ui/icon'
import { Input, inputVariants } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'

const inputGroupVariants = cva(
  [
    'group/input-group relative flex h-9 min-w-0 w-full items-center rounded-md outline-none transition-colors',
    'has-[>textarea]:h-auto',
    'has-[>[data-align=block-end]]:h-auto has-[>[data-align=block-end]]:flex-col',
    'has-[>[data-align=block-start]]:h-auto has-[>[data-align=block-start]]:flex-col',
    'has-[>[data-align=block-end]]:[&>input]:pt-3 has-[>[data-align=block-start]]:[&>input]:pb-3',
    'has-[>[data-align=inline-end]]:[&>input]:pr-1.5 has-[>[data-align=inline-start]]:[&>input]:pl-1.5',
    'in-data-[slot=combobox-content]:focus-within:border-inherit',
  ].join(' '),
  {
    variants: {
      variant: {
        default:
          'border border-input bg-transparent shadow-xs focus-within:border-ring aria-invalid:border-destructive dark:bg-input/30 dark:aria-invalid:border-destructive/50',
        ghost:
          'border border-transparent bg-transparent shadow-none focus-within:border-ring aria-invalid:border-destructive dark:bg-transparent dark:aria-invalid:border-destructive/50',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
)

type InputGroupProps = React.ComponentProps<'div'> & VariantProps<typeof inputGroupVariants>

function InputGroup({ className, variant = 'default', ...props }: InputGroupProps) {
  return (
    <div
      data-slot="input-group"
      data-variant={variant}
      role="group"
      className={cn(inputGroupVariants({ variant }), className)}
      {...props}
    />
  )
}

const inputGroupAddonVariants = cva(
  // shadcn upstream: `transition-colors` + `transition-opacity` are meant to stack
  // eslint-disable-next-line tailwindcss/no-contradicting-classname
  "flex h-auto cursor-text items-center justify-center gap-2 py-1.5 text-sm font-medium text-muted-foreground transition-colors transition-opacity select-none group-data-[disabled=true]/input-group:opacity-50 [&>kbd]:rounded-[calc(var(--radius)-5px)] [&>svg:not([class*='size-'])]:size-4",
  {
    variants: {
      align: {
        'inline-start': 'order-first pl-2 has-[>button]:-ml-1 has-[>kbd]:ml-[-0.15rem]',
        'inline-end': 'order-last pr-2 has-[>button]:-mr-1 has-[>kbd]:mr-[-0.15rem]',
        'block-start':
          'order-first w-full justify-start px-2.5 pt-2 group-has-[>input]/input-group:pt-2 [.border-b]:pb-2',
        'block-end': 'order-last w-full justify-start px-2.5 pb-2 group-has-[>input]/input-group:pb-2 [.border-t]:pt-2',
      },
    },
    defaultVariants: {
      align: 'inline-start',
    },
  },
)

function InputGroupAddon({
  className,
  align = 'inline-start',
  ...props
}: React.ComponentProps<'div'> & VariantProps<typeof inputGroupAddonVariants>) {
  return (
    <div
      role="group"
      data-slot="input-group-addon"
      data-align={align}
      className={cn(inputGroupAddonVariants({ align }), className)}
      onClick={(e) => {
        if ((e.target as HTMLElement).closest('button')) {
          return
        }
        e.currentTarget.parentElement?.querySelector('input')?.focus()
      }}
      {...props}
    />
  )
}

const inputGroupButtonVariants = cva('flex items-center gap-2 text-sm shadow-none', {
  variants: {
    size: {
      xs: "h-6 gap-1 rounded-[calc(var(--radius)-5px)] px-1.5 [&>svg:not([class*='size-'])]:size-3.5",
      sm: '',
      'icon-xs': 'size-6 rounded-[calc(var(--radius)-5px)] p-0 has-[>svg]:p-0',
      'icon-sm': 'size-8 p-0 has-[>svg]:p-0',
    },
  },
  defaultVariants: {
    size: 'xs',
  },
})

function InputGroupButton({
  className,
  type = 'button',
  variant = 'ghost',
  size = 'xs',
  ...props
}: DistributiveOmit<React.ComponentProps<typeof Button>, 'size'> & VariantProps<typeof inputGroupButtonVariants>) {
  return (
    <Button
      type={type}
      data-size={size}
      variant={variant}
      className={cn(inputGroupButtonVariants({ size }), className)}
      {...props}
    />
  )
}

function InputGroupText({ className, ...props }: React.ComponentProps<'span'>) {
  return (
    <span
      className={cn(
        "flex items-center gap-2 text-sm text-muted-foreground [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4",
        className,
      )}
      {...props}
    />
  )
}

type InputGroupInputProps = React.ComponentPropsWithoutRef<'input'> & VariantProps<typeof inputVariants>
const InputGroupInput = React.forwardRef<HTMLInputElement, InputGroupInputProps>(function InputGroupInput(
  { className, ...props },
  ref,
) {
  return (
    <Input
      data-slot="input-group-control"
      className={cn(
        'flex-1 rounded-none border-0 bg-transparent shadow-none ring-0 focus-visible:ring-0 aria-invalid:ring-0 dark:bg-transparent',
        className,
      )}
      ref={ref}
      {...props}
    />
  )
})

type InputGroupTextareaProps = React.ComponentPropsWithoutRef<'textarea'>
const InputGroupTextarea = React.forwardRef<HTMLTextAreaElement, InputGroupTextareaProps>(function InputGroupTextarea(
  { className, ...props },
  ref,
) {
  return (
    <Textarea
      data-slot="input-group-control"
      className={cn(
        'flex-1 resize-none rounded-none border-0 bg-transparent py-2 shadow-none ring-0 focus-visible:ring-0 aria-invalid:ring-0 dark:bg-transparent',
        className,
      )}
      ref={ref}
      {...props}
    />
  )
})

export { InputGroup, InputGroupAddon, InputGroupButton, InputGroupText, InputGroupInput, InputGroupTextarea }

type XInputProps = React.ComponentProps<typeof Input> & {
  icon?: IconType
  iconPosition?: 'start' | 'end'
  iconSize?: number | string
  iconClassName?: string
  inputGroupProps?: React.ComponentProps<typeof InputGroup>
  startAddon?: React.ReactNode
  startAddonProps?: React.ComponentProps<typeof InputGroupAddon>
  endAddon?: React.ReactNode
  endAddonProps?: React.ComponentProps<typeof InputGroupAddon>
}

const XInput = React.forwardRef<HTMLInputElement, XInputProps>(function XInput(props, ref) {
  const {
    className,
    variant = 'default',
    inputSize = 'default',
    disabled,
    icon,
    iconPosition = 'start',
    iconSize,
    iconClassName,
    startAddon,
    startAddonProps,
    endAddon,
    endAddonProps,
    inputGroupProps,
    ...rest
  } = props
  const iconElement =
    icon !== undefined ? <Icon icon={icon} size="default" iconSize={iconSize} iconClassName={iconClassName} /> : null
  const resolvedStartAddon = iconPosition === 'start' && startAddon === undefined ? iconElement : startAddon
  const resolvedEndAddon = iconPosition === 'end' && endAddon === undefined ? iconElement : endAddon
  const hasInputGroupProps =
    'inputGroupProps' in props ||
    icon !== undefined ||
    'startAddon' in props ||
    'startAddonProps' in props ||
    'endAddon' in props ||
    'endAddonProps' in props

  if (!hasInputGroupProps) {
    return (
      <Input ref={ref} className={className} variant={variant} inputSize={inputSize} disabled={disabled} {...rest} />
    )
  }

  return (
    <InputGroup
      variant={variant}
      aria-invalid={rest['aria-invalid']}
      data-disabled={disabled}
      {...inputGroupProps}
      className={cn(inputVariants({ variant, inputSize }), 'p-0', inputGroupProps?.className)}
    >
      {resolvedStartAddon !== null && resolvedStartAddon !== undefined && (
        <InputGroupAddon align="inline-start" {...startAddonProps}>
          {resolvedStartAddon}
        </InputGroupAddon>
      )}
      <InputGroupInput
        ref={ref}
        className={className}
        variant={variant}
        inputSize={inputSize}
        disabled={disabled}
        {...rest}
      />
      {resolvedEndAddon !== null && resolvedEndAddon !== undefined && (
        <InputGroupAddon align="inline-end" {...endAddonProps}>
          {resolvedEndAddon}
        </InputGroupAddon>
      )}
    </InputGroup>
  )
})

export type { XInputProps }
export { XInput }
