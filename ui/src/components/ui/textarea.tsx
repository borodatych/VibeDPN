import * as React from 'react'

import { cn } from '@/utils'

type TextareaProps = React.ComponentPropsWithoutRef<'textarea'>

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea({ className, ...props }, ref) {
  return (
    <textarea
      data-slot="textarea"
      ref={ref}
      className={cn(
        'flex field-sizing-content min-h-16 w-full rounded-md border border-input bg-transparent px-2.5 py-2 text-base shadow-xs transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive md:text-sm dark:bg-input/30 dark:aria-invalid:border-destructive/50',
        className,
      )}
      {...props}
    />
  )
})

export { Textarea }
