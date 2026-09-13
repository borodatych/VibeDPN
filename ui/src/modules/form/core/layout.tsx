import { cn } from '@/utils'
import { cva, type VariantProps } from 'class-variance-authority'
import { Slot } from 'radix-ui'
import { forwardRef, type ComponentPropsWithoutRef, type ElementType, type ReactElement, type ReactNode } from 'react'

export const formLayoutVariants = cva('flex flex-col', {
  variants: {
    size: {
      sm: 'form-sm',
      md: 'form-md',
    },
    spacing: {
      filter: 'mb-6',
    },
  },
  defaultVariants: {
    size: null,
    spacing: null,
  },
})
export type FormLayoutVariantProps = VariantProps<typeof formLayoutVariants>

export type FLayoutProps = FormLayoutVariantProps & {
  children?: ReactNode
  className?: string
  formProps?: Omit<ComponentPropsWithoutRef<'form'>, 'children' | 'onSubmit'>
  onSubmit?: ComponentPropsWithoutRef<'form'>['onSubmit']
  as?: ElementType
  asChild?: boolean
  fields?: boolean | FFieldsProps
}
export const FLayout = ({
  children,
  className,
  formProps,
  onSubmit,
  size,
  spacing,
  as,
  asChild,
  fields,
}: FLayoutProps): ReactElement => {
  const layoutClassName = cn(formLayoutVariants({ size, spacing }), formProps?.className, className)
  const Comp = asChild ? Slot.Root : (as ?? 'div')
  const wrapperProps =
    as !== 'form'
      ? {
          className: layoutClassName,
        }
      : {
          ...formProps,
          className: layoutClassName,
          onSubmit,
          noValidate: true,
        }
  const fieldsProps = !fields ? undefined : typeof fields === 'object' ? fields : {}
  const childrenInFields = fields ? <FFields {...fieldsProps}>{children}</FFields> : children
  return <Comp {...wrapperProps}>{childrenInFields}</Comp>
}

export const formFieldsVariants = cva('flex flex-col', {
  variants: {
    gap: {
      default: 'gap-x-form-fields-xgap gap-y-form-fields-ygap',
    },
  },
  defaultVariants: {
    gap: 'default',
  },
})
export type FormFieldsVariantProps = VariantProps<typeof formFieldsVariants>
export type FFieldsProps = ComponentPropsWithoutRef<'div'> & FormFieldsVariantProps
export const FFields = forwardRef<HTMLDivElement, FFieldsProps>(({ className, gap, ...props }, ref) => {
  return <div ref={ref} className={cn(formFieldsVariants({ gap }), className)} {...props} />
})
FFields.displayName = 'FFields'

export const formSectionsVariants = cva('flex flex-col', {
  variants: {
    gap: {
      default: 'gap-x-form-sections-xgap gap-y-form-sections-ygap',
    },
  },
  defaultVariants: {
    gap: 'default',
  },
})
export type FormSectionsVariantProps = VariantProps<typeof formSectionsVariants>
export type FSectionsProps = ComponentPropsWithoutRef<'div'> & FormSectionsVariantProps
export const FSections = forwardRef<HTMLDivElement, FSectionsProps>(({ className, gap, ...props }, ref) => {
  return <div ref={ref} className={cn(formSectionsVariants({ gap }), className)} {...props} />
})
FSections.displayName = 'FSections'

export const formFooterVariants = cva('flex flex-col not-first:mt-form-sections-ygap', {
  variants: {
    gap: {
      default: '',
    },
  },
  defaultVariants: {
    gap: 'default',
  },
})
export type FormFooterVariantProps = VariantProps<typeof formFooterVariants>
export type FFooterProps = ComponentPropsWithoutRef<'div'> & FormFooterVariantProps
export const FFooter = forwardRef<HTMLDivElement, FFooterProps>(({ className, gap, ...props }, ref) => {
  return <div ref={ref} className={cn(formFooterVariants({ gap }), className)} {...props} />
})
FFooter.displayName = 'FFooter'
