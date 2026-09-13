import { cn } from '@/utils'
import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

type IconType =
  React.ElementType<{ className?: string; 'aria-hidden'?: boolean }> | React.ReactElement<{ className?: string }>

const iconVariants = cva('', {
  variants: {
    size: {
      default: 'size-4',
      xs: 'size-3',
      sm: 'size-4',
      lg: 'size-5',
      xl: 'size-5',
      '2xl': 'size-5',
    },
  },
  defaultVariants: {
    size: 'default',
  },
})

const getIconSizeClassName = (iconSize: number | string | undefined) => {
  if (!iconSize) {
    return undefined
  }

  return typeof iconSize === 'number' ? `size-${iconSize}` : iconSize
}

type IconProps = VariantProps<typeof iconVariants> & {
  icon?: IconType
  iconSize?: number | string
  className?: string
  iconClassName?: string
  'aria-hidden'?: boolean
}

function Icon({
  icon,
  size = 'default',
  iconSize,
  className,
  iconClassName,
  'aria-hidden': ariaHidden = true,
}: IconProps) {
  if (!icon) {
    return null
  }

  const resolvedIconClassName = cn(iconVariants({ size }), getIconSizeClassName(iconSize), className, iconClassName)

  if (React.isValidElement<{ className?: string; 'aria-hidden'?: boolean }>(icon)) {
    return React.cloneElement(icon, {
      className: cn(resolvedIconClassName, icon.props.className),
      'aria-hidden': icon.props['aria-hidden'] ?? ariaHidden,
    })
  }

  const Component = icon as React.ElementType<{ className?: string; 'aria-hidden'?: boolean }>
  return <Component className={resolvedIconClassName} aria-hidden={ariaHidden} />
}

export { Icon, iconVariants, type IconProps, type IconType }
