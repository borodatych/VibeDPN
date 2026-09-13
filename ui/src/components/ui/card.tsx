import { cva, type VariantProps } from 'class-variance-authority'

import type { SectionProps } from '@/components/ui/section'
import { Section } from '@/components/ui/section'
import { cn } from '@/utils'

const cardVariants = cva('border shadow-xs', {
  variants: {
    border: {
      muted: 'border-foreground/20',
      bright: 'border-foreground/30',
      none: 'border-0',
    },
    background: {
      true: 'bg-card text-card-foreground',
      false: 'bg-transparent',
    },
    compact: {
      true: '[--section-px:1.25rem] [--section-py:1rem] max-sm:[--section-px:1rem] max-sm:[--section-py:1rem]',
      false: '[--section-px:1.70rem] [--section-py:1.5rem] max-sm:[--section-px:1rem] max-sm:[--section-py:1rem]',
    },
  },
  defaultVariants: {
    border: 'muted',
    background: true,
    compact: false,
  },
})

type CardProps = SectionProps & VariantProps<typeof cardVariants> & { bare?: boolean }

function Card({ className, border, background, compact, bare, ...props }: CardProps) {
  return (
    <Section
      data-slot={bare ? undefined : 'card'}
      className={cn(bare ? undefined : cardVariants({ border, background, compact }), className)}
      {...props}
    />
  )
}

export { Card }
export type { CardProps }
