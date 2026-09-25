import { Button } from '@/components/ui/button'
import { useT } from '@/modules/i18n/use-t'
import type { DistributiveOmit } from '@/types'
import { cn } from '@/utils'
import { ChevronLeftIcon, ChevronRightIcon, MoreHorizontalIcon } from 'lucide-react'
import * as React from 'react'

function Pagination({ className, ...props }: React.ComponentProps<'nav'>) {
  const t = useT()
  return (
    <nav
      role="navigation"
      aria-label={t('ui.pagination')}
      data-slot="pagination"
      className={cn('mx-auto flex w-full justify-center', className)}
      {...props}
    />
  )
}

function PaginationContent({ className, ...props }: React.ComponentProps<'ul'>) {
  return <ul data-slot="pagination-content" className={cn('flex items-center gap-1', className)} {...props} />
}

function PaginationItem({ ...props }: React.ComponentProps<'li'>) {
  return <li data-slot="pagination-item" {...props} />
}

// Derives straight from Button (which already carries InferNavigation.LinkProps), so
// route/to/href + link options are typed; only `variant` is owned by PaginationLink.
type PaginationLinkProps = {
  isActive?: boolean
} & DistributiveOmit<React.ComponentProps<typeof Button>, 'variant'>

function PaginationLink({
  className,
  isActive,
  size = 'icon',
  replace = true,
  prefetch = false,
  ...props
}: PaginationLinkProps) {
  return (
    <Button
      aria-current={isActive ? 'page' : undefined}
      data-slot="pagination-link"
      data-active={isActive}
      prefetch={prefetch}
      replace={replace}
      {...props}
      variant={isActive ? 'secondary' : 'ghost'}
      size={size}
      className={cn(className, isActive && 'pointer-events-none opacity-50')}
    />
  )
}

function PaginationPrevious({
  className,
  text,
  ...props
}: React.ComponentProps<typeof PaginationLink> & { text?: string }) {
  const t = useT()
  return (
    <PaginationLink
      aria-label={t('ui.pagination.goPrevious')}
      size="default"
      className={cn('pl-2!', className)}
      {...props}
    >
      <ChevronLeftIcon data-icon="inline-start" />
      <span className="hidden sm:block">{text ?? t('ui.pagination.previous')}</span>
    </PaginationLink>
  )
}

function PaginationNext({
  className,
  text,
  ...props
}: React.ComponentProps<typeof PaginationLink> & { text?: string }) {
  const t = useT()
  return (
    <PaginationLink aria-label={t('ui.pagination.goNext')} size="default" className={cn('pr-2!', className)} {...props}>
      <span className="hidden sm:block">{text ?? t('ui.pagination.next')}</span>
      <ChevronRightIcon data-icon="inline-end" />
    </PaginationLink>
  )
}

function PaginationEllipsis({ className, ...props }: React.ComponentProps<'span'>) {
  const t = useT()
  return (
    <span
      aria-hidden
      data-slot="pagination-ellipsis"
      className={cn(
        "flex size-9 items-center justify-center text-muted-foreground/60 [&_svg:not([class*='size-'])]:size-4",
        className,
      )}
      {...props}
    >
      <MoreHorizontalIcon />
      <span className="sr-only">{t('ui.pagination.morePages')}</span>
    </span>
  )
}

export {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
}
