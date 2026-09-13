import { Spinner } from '@/components/ui/spinner'
import { Link, type AppLinkProps } from '@/lib/navigation'
import { cn } from '@/utils'
import { splitLinkProps } from '@point0/react-dom/router'
import { cva, type VariantProps } from 'class-variance-authority'
import { Slot } from 'radix-ui'
import * as React from 'react'
import { Icon, type IconProps, type IconType } from './icon'
import { Popover, PopoverAnchor, PopoverContent } from './popover'
import { Tooltip, TooltipContent, TooltipTrigger } from './tooltip'

type ButtonSize = NonNullable<VariantProps<typeof buttonVariants>['size']>

const buttonVariants = cva(
  "group/button relative inline-flex shrink-0 cursor-pointer items-center justify-center rounded-md border border-transparent bg-clip-padding font-accent text-sm font-semibold whitespace-nowrap  outline-none select-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-[3px] aria-invalid:ring-destructive/20 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground hover:bg-primary-hover',
        // google: 'bg-[#DB4437] text-white hover:bg-[#C43C30]',
        // google: 'border-[#DB4437] text-[#DB4437] hover:border-[#C43C30] hover:text-[#C43C30]',
        // outline:
        //   'border-foreground bg-background text-foreground hover:border-foreground/50 hover:text-foreground/80 aria-expanded:bg-foreground aria-expanded:text-foreground',
        outline:
          'border-primary bg-background text-primary hover:border-primary-hover hover:bg-link-hover/7 hover:text-primary-hover aria-expanded:bg-link-hover/7 aria-expanded:text-primary-hover dark:border-link dark:text-link dark:hover:bg-link-hover/30',
        secondary:
          'bg-secondary text-secondary-foreground hover:bg-secondary-hover aria-expanded:bg-secondary aria-expanded:text-secondary-foreground',
        // Bordered, input-looking sibling of `secondary`: rests as an outline on the page background, fills on hover.
        'outline-secondary':
          'border-input bg-background text-secondary-foreground shadow-xs hover:bg-secondary hover:text-secondary-foreground aria-expanded:bg-secondary dark:bg-input/30 dark:hover:bg-input/50',
        ghost:
          'hover:bg-muted hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground dark:hover:bg-muted/50',
        destructive:
          'bg-destructive/10 text-destructive hover:bg-destructive/20 focus-visible:border-destructive/40 focus-visible:ring-destructive/20 dark:bg-destructive/20 dark:hover:bg-destructive/30 dark:focus-visible:ring-destructive/40',
        success:
          'bg-success/10 text-success hover:bg-success/20 focus-visible:border-success/40 focus-visible:ring-success/20 dark:bg-success/20 dark:hover:bg-success/30 dark:focus-visible:ring-success/40',
        warning:
          'bg-warning/10 text-warning hover:bg-warning/20 focus-visible:border-warning/40 focus-visible:ring-warning/20 dark:bg-warning/20 dark:hover:bg-warning/30 dark:focus-visible:ring-warning/40',
        info: 'bg-info/10 text-info hover:bg-info/20 focus-visible:border-info/40 focus-visible:ring-info/20 dark:bg-info/20 dark:hover:bg-info/30 dark:focus-visible:ring-info/40',
        link: 'link',
      },
      size: {
        default:
          'h-9 gap-1.5 px-2.5 in-data-[slot=button-group]:rounded-md has-data-[icon=inline-end]:pr-2 has-data-[icon=inline-start]:pl-2',
        xs: "h-6 gap-1 rounded-[min(var(--radius-md),8px)] px-2 text-xs in-data-[slot=button-group]:rounded-md has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 [&_svg:not([class*='size-'])]:size-3",
        sm: 'h-8 gap-1 rounded-[min(var(--radius-md),10px)] px-2.5 in-data-[slot=button-group]:rounded-md has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5',
        lg: 'h-10 gap-1.5 px-2.5 text-base has-data-[icon=inline-end]:pr-3 has-data-[icon=inline-start]:pl-3',
        xl: 'h-11 gap-2 px-3 text-base has-data-[icon=inline-end]:pr-3.5 has-data-[icon=inline-start]:pl-3.5',
        '2xl': 'h-12 gap-2.5 px-3.5 text-base has-data-[icon=inline-end]:pr-4 has-data-[icon=inline-start]:pl-4',
        icon: 'size-9',
        'icon-default': 'size-9',
        'icon-xs':
          "size-6 rounded-[min(var(--radius-md),8px)] in-data-[slot=button-group]:rounded-md [&_svg:not([class*='size-'])]:size-3",
        'icon-sm': 'size-8 rounded-[min(var(--radius-md),10px)] in-data-[slot=button-group]:rounded-md',
        'icon-lg': 'size-10',
        'icon-xl': 'size-11',
        'icon-2xl': 'size-12',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
)

const Button = React.forwardRef<
  HTMLButtonElement,
  React.ComponentProps<'button'> &
    VariantProps<typeof buttonVariants> & {
      asChild?: boolean
      icon?: IconType
      iconSize?: number
      hint?: string
      confirm?: string
      loading?: boolean
      iconPosition?: 'start' | 'end'
      iconClassName?: string
      contentClassName?: string
    } & AppLinkProps & {
      // `target` is a native <a> concern, not a navigation prop, so it lives here.
      target?: React.ComponentProps<'a'>['target']
    }
>((allProps, ref) => {
  const [linkPropsRaw, restProps, isLink] = splitLinkProps(allProps)
  const {
    className,
    variant = 'default',
    size,
    asChild = false,
    children,
    icon,
    onClick,
    hint,
    confirm,
    loading = false,
    iconSize,
    iconPosition = 'start',
    iconClassName,
    contentClassName,
    disabled,
    target,
    ...props
  } = restProps
  const [popoverOpen, setPopoverOpen] = React.useState(false)
  const linkProps = isLink ? { ...linkPropsRaw, ...(target !== undefined ? { target } : {}) } : {}
  const Comp = asChild ? Slot.Root : isLink ? (Link as unknown as 'button') : 'button'

  const hasNonIconContent = !!children

  // const buttonSize = (size ?? 'default') as ButtonSize
  const buttonSize = !hasNonIconContent
    ? (() => {
        switch (size) {
          case 'xs':
            return 'icon-xs'
          case 'sm':
            return 'icon-sm'
          case 'lg':
            return 'icon-lg'
          case 'xl':
            return 'icon-xl'
          case '2xl':
            return 'icon-2xl'
          // Already an icon size — keep it. (Without these, e.g. `icon-lg` fell through to `default` and collapsed
          // to `icon`/36px, so an icon-only `size="icon-lg"` button silently shrank.)
          case 'icon':
          case 'icon-xs':
          case 'icon-sm':
          case 'icon-lg':
          case 'icon-xl':
          case 'icon-2xl':
            return size
          default:
            return 'icon'
        }
      })()
    : (size ?? 'default')

  const iconSizeByButtonSize = {
    default: 'default',
    xs: 'xs',
    sm: 'sm',
    lg: 'lg',
    xl: 'xl',
    '2xl': '2xl',
    icon: 'default',
    'icon-default': 'default',
    'icon-xs': 'xs',
    'icon-sm': 'sm',
    'icon-lg': 'lg',
    'icon-xl': 'xl',
    'icon-2xl': '2xl',
  } satisfies Record<ButtonSize, NonNullable<IconProps['size']>>
  const resolvedIconSize = iconSizeByButtonSize[buttonSize]

  const spinnerSizeByButtonSize = {
    default: 'default',
    xs: 'xs',
    sm: 'sm',
    lg: 'lg',
    xl: 'lg',
    '2xl': 'lg',
    'icon-xs': 'xs',
    'icon-sm': 'sm',
    icon: 'default',
    'icon-default': 'default',
    'icon-lg': 'lg',
    'icon-xl': 'lg',
    'icon-2xl': 'lg',
  } satisfies Record<ButtonSize, React.ComponentProps<typeof Spinner>['size']>

  // eslint-disable-next-line @typescript-eslint/no-unnecessary-condition
  const spinnerSize = spinnerSizeByButtonSize[buttonSize] ?? 'default'

  // Slot.Root must receive a single element child; we can't safely inject icon siblings here.
  if (asChild) {
    return (
      <Comp
        ref={ref}
        data-slot="button"
        data-variant={variant}
        data-size={buttonSize}
        data-icon={icon ? (iconPosition === 'start' ? 'inline-start' : 'inline-end') : undefined}
        className={cn(buttonVariants({ variant, size: buttonSize, className }))}
        {...props}
        {...linkProps}
      >
        {children}
      </Comp>
    )
  }

  const trigger = (
    <Comp
      ref={ref}
      data-slot="button"
      data-variant={variant}
      data-size={buttonSize}
      data-icon={icon ? iconPosition : undefined}
      aria-busy={loading || undefined}
      disabled={disabled || loading}
      className={cn(buttonVariants({ variant, size: buttonSize, className }))}
      onClick={(e) => {
        if (confirm) {
          e.preventDefault()
          e.stopPropagation()
          setPopoverOpen(true)
          return
        } else {
          onClick?.(e)
        }
      }}
      {...props}
      {...linkProps}
    >
      <span
        className={cn(
          'pointer-events-none absolute inset-0 grid place-items-center transition-opacity duration-200 ease-out',
          loading ? 'opacity-100' : 'opacity-0',
        )}
      >
        <Spinner size={spinnerSize} />
      </span>
      {iconPosition === 'start' ? (
        <Icon icon={icon} size={resolvedIconSize} iconSize={iconSize} iconClassName={iconClassName} />
      ) : null}
      <span
        className={cn(
          'transition-opacity duration-200 ease-out',
          loading ? 'opacity-30' : 'opacity-100',
          contentClassName,
        )}
      >
        {children}
      </span>
      {iconPosition === 'end' ? (
        <Icon icon={icon} size={resolvedIconSize} iconSize={iconSize} iconClassName={iconClassName} />
      ) : null}
    </Comp>
  )

  const confirmPopoverContent = !!confirm && (
    <PopoverContent className="flex w-48 flex-col gap-3">
      <div className="">{confirm}</div>
      <div className="flex w-full flex-row items-stretch justify-stretch gap-1">
        <Button
          variant="secondary"
          size="sm"
          className="flex-1"
          onClick={() => {
            setPopoverOpen(false)
            document.body.focus()
          }}
        >
          No
        </Button>
        <Button
          variant="destructive"
          size="sm"
          className="flex-1"
          onClick={(e) => {
            setPopoverOpen(false)
            onClick?.(e)
          }}
        >
          Yes
        </Button>
      </div>
    </PopoverContent>
  )

  if (confirm && hint) {
    return (
      <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
        <Tooltip delayDuration={400}>
          <PopoverAnchor asChild>
            <TooltipTrigger asChild>{trigger}</TooltipTrigger>
          </PopoverAnchor>
          <TooltipContent>{hint}</TooltipContent>
        </Tooltip>
        {confirmPopoverContent}
      </Popover>
    )
  }

  if (confirm) {
    return (
      <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
        <PopoverAnchor asChild>{trigger}</PopoverAnchor>
        {confirmPopoverContent}
      </Popover>
    )
  }

  if (hint) {
    return (
      <Tooltip delayDuration={400}>
        <TooltipTrigger asChild>{trigger}</TooltipTrigger>
        <TooltipContent>{hint}</TooltipContent>
      </Tooltip>
    )
  }

  return trigger
})

Button.displayName = 'Button'

export { Button, buttonVariants, type IconType as ButtonIconType, type ButtonSize }

export const buttonsVariants = cva('flex flex-row flex-wrap', {
  variants: {
    gap: {
      default: 'gap-buttons-gap-sm',
    },
  },
  defaultVariants: {
    gap: 'default',
  },
})
export type FormButtonsVariantProps = VariantProps<typeof buttonsVariants>
export type ButtonsProps = React.ComponentPropsWithoutRef<'div'> & FormButtonsVariantProps
export const Buttons = React.forwardRef<HTMLDivElement, ButtonsProps>(({ className, gap, ...props }, ref) => {
  return <div ref={ref} className={cn(buttonsVariants({ gap }), className)} {...props} />
})
Buttons.displayName = 'Buttons'
