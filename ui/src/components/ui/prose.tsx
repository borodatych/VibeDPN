import { cn } from '@/utils'
import { cva, type VariantProps } from 'class-variance-authority'
import type { ComponentProps } from 'react'

const proseVariants = cva(
  [
    'prose max-w-none',
    '**:data-code-block:not-first:mt-8 **:data-code-block:not-last:mb-8',
    'prose-headings:relative prose-headings:scroll-mt-24 prose-headings:font-title prose-headings:font-semibold prose-headings:tracking-tight prose-headings:text-balance prose-headings:text-accent-foreground prose-headings:not-first:pt-4',
    '**:data-heading-anchor:absolute **:data-heading-anchor:top-1/2 **:data-heading-anchor:-left-7 **:data-heading-anchor:mt-2 **:data-heading-anchor:-translate-y-1/2 **:data-heading-anchor:opacity-0 [&_:is(h1,h2,h3,h4,h5,h6):focus-within_[data-heading-anchor]]:opacity-100 [&_:is(h1,h2,h3,h4,h5,h6):hover_[data-heading-anchor]]:opacity-100',
    'max-sm:**:data-heading-anchor:static max-sm:**:data-heading-anchor:mt-0 max-sm:**:data-heading-anchor:inline-block max-sm:**:data-heading-anchor:translate-y-0 max-sm:**:data-heading-anchor:opacity-100',
    'prose-lead:text-muted-foreground',
    'prose-a:font-normal prose-a:text-link prose-a:no-underline prose-a:hover:text-link-hover prose-a:hover:underline',
    'prose-blockquote:border-border prose-blockquote:font-normal prose-blockquote:text-foreground',
    'prose-strong:font-semibold prose-strong:text-foreground',
    'prose-em:text-foreground',
    'prose-kbd:rounded-md prose-kbd:border prose-kbd:border-border prose-kbd:bg-muted prose-kbd:px-1.5 prose-kbd:py-0.5 prose-kbd:font-mono prose-kbd:text-xs',
    'prose-code:inline-block prose-code:rounded-md prose-code:border prose-code:border-border prose-code:bg-muted prose-code:px-1.5 prose-code:py-0.5 prose-code:font-mono prose-code:text-sm prose-code:font-normal prose-code:text-foreground prose-code:before:content-none prose-code:after:content-none max-sm:prose-code:text-xs',
    // Inline code inside headings: scale with the heading (em-sized) and center on the
    // line so the chip stays put instead of dropping below the baseline.
    '[&_:is(h1,h2,h3,h4,h5,h6)_code]:align-middle [&_:is(h1,h2,h3,h4,h5,h6)_code]:text-[0.85em] [&_:is(h1,h2,h3,h4,h5,h6)_code]:leading-tight [&_:is(h1,h2,h3,h4,h5,h6)_code]:font-medium',
    'prose-pre:rounded-xl prose-pre:border prose-pre:border-border prose-pre:bg-muted prose-pre:text-foreground',
    'prose-ol:pl-6 prose-ul:pl-6 prose-li:marker:text-muted-foreground',
    'prose-dt:font-semibold prose-dt:text-foreground prose-dd:text-muted-foreground',
    // `block` (+ w-max/max-w-full) makes a wide table scroll inside itself instead of stretching the page — `overflow`
    // is ignored on a `display:table` box, so the table must become a block to become its own scroll container.
    'prose-table:my-8 prose-table:block prose-table:w-max prose-table:max-w-full prose-table:overflow-x-auto prose-thead:border-border prose-tr:border-border prose-th:font-title prose-th:font-semibold prose-td:text-foreground',
    'prose-figure:my-8 prose-figcaption:text-sm prose-figcaption:text-muted-foreground prose-img:rounded-xl',
    'prose-hr:border-border',
  ],
  {
    variants: {
      size: {
        sm: [
          'prose-h1:mb-4 prose-h1:text-3xl prose-h1:not-first:mt-6 md:prose-h1:text-4xl',
          'prose-h2:mb-4 prose-h2:text-2xl prose-h2:not-first:mt-6 md:prose-h2:text-3xl',
          'prose-h3:mb-3 prose-h3:text-xl prose-h3:not-first:mt-4 md:prose-h3:text-2xl',
          'prose-h4:mb-3 prose-h4:text-lg prose-h4:not-first:mt-2 md:prose-h4:text-xl',
          'prose-p:max-w-3xl prose-p:text-sm prose-p:leading-[1.65] prose-p:text-foreground',
          'prose-li:max-w-3xl prose-li:text-sm prose-li:leading-[1.65] prose-li:text-foreground',
        ],
        base: [
          'prose-h1:mb-5 prose-h1:text-4xl prose-h1:not-first:mt-10 md:prose-h1:text-5xl',
          'prose-h2:mb-5 prose-h2:text-3xl prose-h2:not-first:mt-10 md:prose-h2:text-4xl',
          'prose-h3:mb-4 prose-h3:text-2xl prose-h3:not-first:mt-6 md:prose-h3:text-3xl',
          'prose-h4:mb-4 prose-h4:text-xl prose-h4:not-first:mt-3 md:prose-h4:text-2xl',
          'prose-p:max-w-3xl prose-p:text-base prose-p:leading-[1.65] prose-p:text-foreground max-sm:prose-p:text-sm',
          'prose-li:max-w-3xl prose-li:text-base prose-li:leading-[1.65] prose-li:text-foreground max-sm:prose-li:text-sm',
        ],
        lg: [
          'prose-h1:mb-5 prose-h1:text-4xl prose-h1:not-first:mt-10 md:prose-h1:text-5xl',
          'prose-h2:mb-5 prose-h2:text-3xl prose-h2:not-first:mt-10 md:prose-h2:text-4xl',
          'prose-h3:mb-4 prose-h3:text-2xl prose-h3:not-first:mt-6 md:prose-h3:text-3xl',
          'prose-h4:mb-4 prose-h4:text-xl prose-h4:not-first:mt-3 md:prose-h4:text-2xl',
          'prose-p:max-w-3xl prose-p:text-lg prose-p:leading-[1.65] prose-p:text-foreground',
          'prose-li:max-w-3xl prose-li:text-lg prose-li:leading-[1.65] prose-li:text-foreground',
        ],
      },
    },
    defaultVariants: {
      size: 'base',
    },
  },
)

type ProseProps = ComponentProps<'div'> & VariantProps<typeof proseVariants>

export function Prose({ className, size = 'base', children, ...props }: ProseProps) {
  return (
    <div className={cn(proseVariants({ size }), className)} data-prose-size={size} {...props}>
      {children}
    </div>
  )
}
