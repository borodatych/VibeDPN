import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'

import { useT } from '@/modules/i18n/use-t'
import { cn } from '@/utils'

const spinnerVariants = cva(
  'inline-block shrink-0 animate-spin rounded-full border-2 border-current border-t-transparent align-middle',
  {
    variants: {
      size: {
        xs: 'size-3 border-[2px]',
        sm: 'size-4 border-[2px]',
        default: 'size-4 border-[2px]',
        lg: 'size-6 border-[3px]',
        xl: 'size-8 border-[4px]',
        '2xl': 'size-12 border-[5px]',
        '3xl': 'size-16 border-[7px]',
      },
      type: {
        page: 'm-auto size-16 place-self-center border-5 opacity-50',
        section: 'm-auto size-8 place-self-center border-[3px] opacity-50',
      },
    },
    defaultVariants: {
      size: 'default',
    },
  },
)

/**
 * Loading spinner. Renders an inline `<span>` (not a block `<div>`) so it's valid phrasing content — drop it inside a
 * `<p>`, a button, or a line of text without breaking the DOM. Centering still works: in flex/grid parents and in a
 * `text-center` cell an inline-block behaves the same as a block. Pick a `size`; `type` page/section are full-area
 * variants that center themselves in a flex/grid container.
 *
 * @tags component
 */
function Spinner({
  className,
  size,
  type,
  ...props
}: React.ComponentProps<'span'> & VariantProps<typeof spinnerVariants>) {
  const t = useT()
  return (
    <span
      role="status"
      aria-label={t('app.loading')}
      className={cn(spinnerVariants({ size, type }), className)}
      {...props}
    />
  )
}

export { Spinner, spinnerVariants }
