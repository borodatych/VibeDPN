import { cn } from '@/utils'
import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

const sectionWrapperVariants = cva(
  'group/section flex flex-col text-sm has-[>img:first-child]:pt-0 data-[slot=card]:rounded-xl data-[slot=card]:py-[var(--section-py,1rem)] *:[data-slot=section-header]:mb-0 data-[slot=card]:*:[img:first-child]:rounded-t-xl data-[slot=card]:*:[img:last-child]:rounded-b-xl',
)

const sectionsVariants = cva('flex flex-col', {
  variants: {
    gap: {
      sm: 'gap-sections-gap-sm',
      md: 'gap-sections-gap-md',
      lg: 'gap-sections-gap-lg',
    },
  },
  defaultVariants: {
    gap: 'md',
  },
})

const sectionHeaderVariants = cva(
  '@container/section-header grid auto-rows-min items-start gap-1 group-data-[slot=card]/section:px-(--section-px,1.5rem)',
  {
    variants: {
      size: {
        xs: '[&+*]:mt-3',
        sm: '[&+*]:mt-4',
        default: '[&+*]:mt-6',
        lg: '[&+*]:mt-6',
        xl: '[&+*]:mt-7',
        '2xl': '[&+*]:mt-8 max-md:[&+*]:mt-7',
      },
      shy: {
        false: '',
        true: '',
      },
    },
    compoundVariants: [
      { shy: true, size: 'xs', className: '[&+*]:mt-2' },
      { shy: true, size: 'sm', className: '[&+*]:mt-3' },
      { shy: true, size: 'default', className: '[&+*]:mt-4' },
      { shy: true, size: 'lg', className: '[&+*]:mt-5' },
      { shy: true, size: 'xl', className: '[&+*]:mt-6' },
      { shy: true, size: '2xl', className: '[&+*]:mt-6 max-md:[&+*]:mt-6' },
    ],
    defaultVariants: {
      size: 'default',
      shy: false,
    },
  },
)

const sectionHeaderTitleVariants = cva(
  'flex link-holder items-center gap-2 font-semibold tracking-tight text-balance text-accent-foreground',
  {
    variants: {
      size: {
        xs: 'text-lg leading-[1.2] [&+*]:mt-0.5',
        sm: 'text-xl leading-[1.2] [&+*]:mt-1',
        default: 'text-3xl leading-[1.2] max-md:text-2xl max-sm:text-xl [&+*]:mt-2',
        lg: 'text-4xl leading-[1.2] max-md:text-3xl max-sm:text-2xl [&+*]:mt-2.5',
        xl: 'text-5xl leading-[1.2] max-md:text-4xl max-sm:text-3xl [&+*]:mt-3',
        '2xl': 'text-6xl leading-[1.2] max-md:text-5xl max-sm:text-4xl [&+*]:mt-3.5 max-md:[&+*]:mt-3',
      },
      shy: {
        false: 'font-title',
        true: 'font-body',
      },
    },
    compoundVariants: [
      { shy: true, size: 'xs', className: 'text-base leading-[1.2] [&+*]:mt-0.5' },
      { shy: true, size: 'sm', className: 'text-lg leading-[1.2] [&+*]:mt-1' },
      { shy: true, size: 'default', className: 'text-xl leading-[1.2] [&+*]:mt-2' },
      { shy: true, size: 'lg', className: 'text-2xl leading-[1.2] max-md:text-xl [&+*]:mt-2' },
      { shy: true, size: 'xl', className: 'text-3xl leading-[1.2] max-md:text-2xl [&+*]:mt-2.5' },
      { shy: true, size: '2xl', className: 'text-4xl leading-[1.2] max-md:text-3xl [&+*]:mt-3 max-md:[&+*]:mt-3' },
    ],
    defaultVariants: {
      size: 'default',
      shy: false,
    },
  },
)

const sectionHeaderDescriptionVariants = cva('max-w-2xl link-holder text-balance text-muted-foreground', {
  variants: {
    size: {
      xs: 'text-sm leading-[1.5]',
      sm: 'text-base leading-[1.5] max-sm:text-sm',
      default: 'text-lg leading-[1.5] max-sm:text-base',
      lg: 'text-xl leading-[1.5] max-md:text-lg max-sm:text-base',
      xl: 'text-2xl leading-[1.5] max-md:text-xl max-sm:text-lg',
      '2xl': 'text-2xl leading-[1.5] max-md:text-xl max-sm:text-lg',
    },
    shy: {
      false: '',
      true: '',
    },
  },
  compoundVariants: [
    { shy: true, size: 'xs', className: 'text-xs leading-[1.5]' },
    { shy: true, size: 'sm', className: 'text-sm leading-[1.5]' },
    { shy: true, size: 'default', className: 'text-base leading-[1.5]' },
    { shy: true, size: 'lg', className: 'text-base leading-[1.5]' },
    { shy: true, size: 'xl', className: 'text-lg leading-[1.5] max-sm:text-base' },
    { shy: true, size: '2xl', className: 'text-lg leading-[1.5] max-sm:text-base' },
  ],
  defaultVariants: {
    size: 'default',
    shy: false,
  },
})

type SectionWrapperProps = React.ComponentProps<'div'> &
  VariantProps<typeof sectionWrapperVariants> & {
    as?: React.ElementType
    size?: SectionHeaderSize
  }

type SectionsProps = React.ComponentProps<'div'> & VariantProps<typeof sectionsVariants>

type SectionHeaderSize = 'xs' | 'sm' | 'default' | 'lg' | 'xl' | '2xl'

type SectionTitleTag = 'h1' | 'h2' | 'h3' | 'h4' | 'h5' | 'h6'

type SectionTitleH = 1 | 2 | 3 | 4 | 5 | 6

type SectionTitleMarks = Partial<Record<SectionTitleTag, boolean | React.ReactNode>>

type SectionHeaderProps = Omit<React.ComponentProps<'div'>, 'title'> &
  VariantProps<typeof sectionHeaderVariants> & {
    title?: React.ReactNode
    titleSuffix?: React.ReactNode
    description?: React.ReactNode
    action?: React.ReactNode
    titleClassName?: string
    descriptionClassName?: string
    h?: SectionTitleH
  } & SectionTitleMarks

type SectionProps = Omit<SectionWrapperProps, 'content' | 'title'> & {
  title?: React.ReactNode
  titleSuffix?: React.ReactNode
  description?: React.ReactNode
  action?: React.ReactNode
  h?: SectionTitleH
  headerSize?: SectionHeaderSize
  shy?: boolean
  headerClassName?: string
  titleClassName?: string
  descriptionClassName?: string
  footerClassName?: string
  footer?: React.ReactNode
  content?: React.ReactNode
  contentClassName?: string
} & SectionTitleMarks

function SectionWrapper({ className, size = 'default', as, ...props }: SectionWrapperProps) {
  const Comp = as ?? (props.onSubmit ? 'form' : 'div')

  return <Comp data-slot="section" data-size={size} className={cn(sectionWrapperVariants({ className }))} {...props} />
}

function Sections({ className, gap, ...props }: SectionsProps) {
  return <div data-slot="sections" className={cn(sectionsVariants({ gap, className }))} {...props} />
}

const useSectionTitle = ({
  marks,
  size,
  title,
  h,
}: {
  marks?: SectionTitleMarks
  size?: SectionHeaderSize | null
  title?: React.ReactNode
  h?: SectionTitleH
}) => {
  const [tagFromMark, titleFromMark] = Object.entries(marks ?? {}).find(([, value]) => !!value) || [
    undefined,
    undefined,
  ]
  title ??= !!titleFromMark && typeof titleFromMark !== 'boolean' ? titleFromMark : undefined
  size ??= (
    !tagFromMark
      ? undefined
      : {
          h1: '2xl',
          h2: 'xl',
          h3: 'lg',
          h4: 'default',
          h5: 'sm',
          h6: 'xs',
        }[tagFromMark]
  ) as SectionHeaderSize | undefined
  h ??= (
    !tagFromMark
      ? undefined
      : {
          h1: 1,
          h2: 2,
          h3: 3,
          h4: 4,
          h5: 5,
          h6: 6,
        }[tagFromMark]
  ) as SectionTitleH | undefined
  const TitleTag = (h ? `h${h}` : undefined) as SectionTitleTag | undefined
  return {
    TitleTag,
    size,
    title,
    h,
  }
}

function SectionHeader({
  title: titleProvided,
  titleSuffix,
  description,
  action,
  size: sizeProvided,
  shy: shyProvided,
  className,
  titleClassName,
  descriptionClassName,
  h,
  h1,
  h2,
  h3,
  h4,
  h5,
  h6,
  ...props
}: SectionHeaderProps) {
  const { shy } = useSectionDefaults({ shy: shyProvided })
  const {
    TitleTag = 'span',
    size,
    title,
  } = useSectionTitle({ marks: { h1, h2, h3, h4, h5, h6 }, size: sizeProvided, h, title: titleProvided })

  if (!title && !titleSuffix && !description && !action) {
    return null
  }

  return (
    <div
      data-slot="section-header"
      className={cn(sectionHeaderVariants({ size, shy, className }), action ? 'grid-cols-[minmax(0,1fr)_auto]' : null)}
      {...props}
    >
      <div className="min-w-0">
        {(!!title || !!titleSuffix) && (
          <div className={cn(sectionHeaderTitleVariants({ size, shy, className: titleClassName }))}>
            {title && <TitleTag className="min-w-0">{title}</TitleTag>}
            {titleSuffix}
          </div>
        )}
        {description ? (
          <div className={cn(sectionHeaderDescriptionVariants({ size, shy, className: descriptionClassName }))}>
            {description}
          </div>
        ) : null}
      </div>
      {action ? (
        <div data-slot="section-action" className="self-start justify-self-end">
          {action}
        </div>
      ) : null}
    </div>
  )
}

function Section({
  className,
  size: sizeProvided,
  title: titleProvided,
  titleSuffix,
  description,
  action,
  h: hProvided,
  shy: shyProvided,
  headerSize: headerSizeProvided,
  headerClassName,
  titleClassName,
  descriptionClassName,
  children,
  content,
  contentClassName,
  footerClassName,
  footer,
  h1,
  h2,
  h3,
  h4,
  h5,
  h6,
  ...props
}: SectionProps) {
  content ??= children
  const { shy } = useSectionDefaults({ shy: shyProvided })
  const { size, title, h } = useSectionTitle({
    marks: { h1, h2, h3, h4, h5, h6 },
    size: headerSizeProvided ?? sizeProvided,
    h: hProvided,
    title: titleProvided,
  })
  return (
    <SectionWrapper data-slot="section" size={sizeProvided ?? size} className={className} {...props}>
      <SectionHeader
        title={title}
        titleSuffix={titleSuffix}
        description={description}
        action={action}
        h={h}
        shy={shy}
        size={size}
        className={headerClassName}
        titleClassName={titleClassName}
        descriptionClassName={descriptionClassName}
      />
      {content ? <SectionContent className={contentClassName}>{content}</SectionContent> : null}
      {footer ? <SectionFooter className={footerClassName}>{footer}</SectionFooter> : null}
    </SectionWrapper>
  )
}

function SectionContent({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="section-content"
      className={cn('flex flex-col group-data-[slot=card]/section:px-(--section-px,1.5rem)', className)}
      {...props}
    />
  )
}

function SectionFooter({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="section-footer"
      className={cn(
        'mt-6 flex items-center rounded-b-xl group-data-[slot=card]/section:px-(--section-px,1.5rem) [.border-t]:pt-6 group-data-[size=sm]/section:[.border-t]:pt-4',
        className,
      )}
      {...props}
    />
  )
}

export {
  Section,
  SectionContent,
  SectionFooter,
  SectionHeader,
  sectionHeaderDescriptionVariants,
  sectionHeaderTitleVariants,
  sectionHeaderVariants,
  Sections,
  sectionsVariants,
  SectionWrapper,
}
export type {
  SectionHeaderSize,
  SectionProps,
  SectionsProps,
  SectionTitleH,
  SectionTitleMarks as SectionTitleTagsMarks,
  SectionWrapperProps,
}

export { useSectionTitle as useSectionTitleSize }

export type SectionDefaults = {
  shy?: boolean | null
}
export const sectionDefaults: SectionDefaults = {
  shy: false,
}
export const SectionDefaultsContext = React.createContext<SectionDefaults>(sectionDefaults)
export const SectionDefaultsProvider = ({ children, shy }: React.PropsWithChildren<SectionDefaults>) => {
  const value = React.useMemo(() => ({ shy: shy === undefined ? sectionDefaults.shy : shy }), [shy])
  return <SectionDefaultsContext.Provider value={value}>{children}</SectionDefaultsContext.Provider>
}
export const useSectionDefaults = (overrides: SectionDefaults = {}) => {
  const context = React.useContext(SectionDefaultsContext)
  return { shy: overrides.shy === undefined ? context.shy : overrides.shy }
}
