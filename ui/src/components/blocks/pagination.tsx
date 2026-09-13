import { useChanged } from '@/components/hooks/use-changed'
import { useDefined } from '@/components/hooks/use-defined'
import {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
} from '@/components/ui/pagination'
import { XSelect } from '@/components/ui/select'
import { type AnyUseFFormReturn } from '@/modules/form/core/hook'
import { useFValues } from '@/modules/form/core/values'
import type { AppLinkProps } from '@/lib/navigation'
import { cn } from '@/utils'
import type { Prettify } from '@point0/core'
import { env } from '@point0/core'
import { ChevronsLeftIcon, ChevronsRightIcon } from 'lucide-react'
import { useMemo } from 'react'

export type XPaginationGeneralProps = {
  page?: number
  limit?: number
  total?: number
  nextPage?: number
  prevPage?: number
  pagesCount?: number
}
export type XPaginationExtraProps = {
  replace?: boolean
  className?: string
  variant?: 'rich' | 'poor'
  limitOptions?: number[]
  to?: (page: number) => AppLinkProps | string
  onPageChange?: (page: number) => void
  onLimitChange?: (limit: number) => void
  onPageOrLimitChange?: (page: number, limit: number) => void
  form?: AnyUseFFormReturn<{ page?: number | string | undefined; limit?: number | string | undefined }>
}

export type XPaginationProps = (
  XPaginationGeneralProps | ({ pagination: XPaginationGeneralProps | undefined } & Partial<XPaginationGeneralProps>)
) &
  XPaginationExtraProps

const XPaginationAction = ({
  page,
  disabled,
  label,
  type,
  to: getPageLink,
  onPageChange,
  className,
  replace,
}: {
  page?: number
  disabled?: boolean
  label: string
  type: 'first' | 'previous' | 'next' | 'last'
  to?: (page: number) => AppLinkProps | string
  replace?: boolean
  onPageChange?: (page: number) => void
  className?: string
}) => {
  const isDisabled = disabled || !page
  const linkRaw = !isDisabled && page ? getPageLink?.(page) : undefined
  const link = typeof linkRaw === 'string' ? { to: linkRaw } : linkRaw
  const linkProps = {
    ...link,
    'aria-disabled': isDisabled || undefined,
    tabIndex: isDisabled ? -1 : undefined,
    className: cn(isDisabled && 'pointer-events-none opacity-50', className),
    replace,
    onClick: (event: React.MouseEvent<HTMLButtonElement>) => {
      if (!page || isDisabled) {
        event.preventDefault()
        return
      }
      onPageChange?.(page)
    },
  } satisfies React.ComponentProps<typeof PaginationLink>

  return (
    <PaginationItem>
      {type === 'previous' ? <PaginationPrevious {...linkProps} text="" /> : null}
      {type === 'next' ? <PaginationNext {...linkProps} text="" /> : null}
      {type === 'first' ? (
        <PaginationLink {...linkProps}>
          <span className="sr-only">{label}</span>
          <ChevronsLeftIcon />
        </PaginationLink>
      ) : null}
      {type === 'last' ? (
        <PaginationLink {...linkProps}>
          <span className="sr-only">{label}</span>
          <ChevronsRightIcon />
        </PaginationLink>
      ) : null}
    </PaginationItem>
  )
}

// here if onLimitChange we have dropdown with options, else just show as is
const XPaginationLimit = ({
  className,
  limit,
  onLimitChange,
  limitOptions = [10, 20, 50, 100],
}: {
  className?: string
  limit: number | string
  onLimitChange?: (limit: number) => void
  limitOptions?: number[]
}) => {
  return (
    <div className={cn('flex flex-wrap items-center justify-between gap-3 py-4', className)}>
      <div className="text-sm text-muted-foreground">
        {onLimitChange ? (
          <XSelect
            options={limitOptions.map((option) => ({ value: option, label: `${option} per page` }))}
            value={limit}
            onValueChange={(value) => onLimitChange(Number(value))}
          />
        ) : (
          <span>{limit} per page</span>
        )}
      </div>
    </div>
  )
}

type XPaginationPagesProps = {
  page: number
  nextPage?: number
  prevPage?: number
  pagesCount?: number
  to?: (page: number) => AppLinkProps | string
  replace?: boolean
  onPageChange?: (page: number) => void
  className?: string
}

const XPaginationPage = ({
  page,
  currentPage,
  to: getPageLink,
  replace,
  onPageChange,
}: {
  page: number
  currentPage: number
  to?: (page: number) => AppLinkProps | string
  replace?: boolean
  onPageChange?: (page: number) => void
}) => {
  const linkRaw = getPageLink?.(page)
  const link = typeof linkRaw === 'string' ? { to: linkRaw } : linkRaw
  const isActive = page === currentPage

  return (
    <PaginationItem>
      <PaginationLink
        {...link}
        replace={replace}
        isActive={isActive}
        aria-label={isActive ? `Page ${page}` : `Go to page ${page}`}
        onClick={() => onPageChange?.(page)}
      >
        {page}
      </PaginationLink>
    </PaginationItem>
  )
}

const XPaginationPagesRich = ({
  page,
  pagesCount,
  prevPage,
  nextPage,
  to,
  replace,
  onPageChange,
  className,
}: XPaginationPagesProps) => {
  if (!pagesCount) {
    return (
      <XPaginationPagesPoor
        page={page}
        prevPage={prevPage}
        nextPage={nextPage}
        to={to}
        replace={replace}
        onPageChange={onPageChange}
        className={className}
      />
    )
  }

  const middlePages = [page - 1, page, page + 1].filter((pageNumber) => pageNumber > 1 && pageNumber < pagesCount)
  const showStartEllipsis = middlePages.length > 0 && middlePages[0] > 2
  const showEndEllipsis = middlePages.length > 0 && middlePages.at(-1)! < pagesCount - 1

  return (
    <Pagination className={cn('mx-0 w-auto', className)}>
      <PaginationContent>
        <XPaginationAction
          page={prevPage}
          label="Go to previous page"
          type="previous"
          to={to}
          replace={replace}
          onPageChange={onPageChange}
        />
        <XPaginationPage page={1} currentPage={page} to={to} replace={replace} onPageChange={onPageChange} />
        {showStartEllipsis ? (
          <PaginationItem>
            <PaginationEllipsis />
          </PaginationItem>
        ) : null}
        {middlePages.map((pageNumber) => (
          <XPaginationPage
            key={pageNumber}
            page={pageNumber}
            currentPage={page}
            to={to}
            replace={replace}
            onPageChange={onPageChange}
          />
        ))}
        {showEndEllipsis ? (
          <PaginationItem>
            <PaginationEllipsis />
          </PaginationItem>
        ) : null}
        {pagesCount > 1 ? (
          <XPaginationPage page={pagesCount} currentPage={page} to={to} replace={replace} onPageChange={onPageChange} />
        ) : null}
        <XPaginationAction
          page={nextPage}
          label="Go to next page"
          type="next"
          to={to}
          replace={replace}
          onPageChange={onPageChange}
        />
      </PaginationContent>
    </Pagination>
  )
}

const XPaginationPagesPoor = ({
  page,
  pagesCount,
  nextPage,
  prevPage,
  to,
  replace,
  onPageChange,
  className,
}: XPaginationPagesProps) => {
  return (
    <Pagination className={cn('mx-0 w-auto', className)}>
      <PaginationContent>
        {typeof pagesCount === 'number' ? (
          <XPaginationAction
            page={1}
            disabled={page <= 1}
            label="Go to first page"
            type="first"
            to={to}
            replace={replace}
            onPageChange={onPageChange}
            // className="hidden sm:inline-flex"
          />
        ) : null}
        <XPaginationAction
          page={prevPage}
          label="Go to previous page"
          type="previous"
          to={to}
          replace={replace}
          onPageChange={onPageChange}
        />
        <XPaginationPage
          key={'current'}
          page={page}
          currentPage={page}
          to={to}
          replace={replace}
          onPageChange={onPageChange}
        />
        <XPaginationAction
          page={nextPage}
          label="Go to next page"
          type="next"
          to={to}
          replace={replace}
          onPageChange={onPageChange}
        />
        {typeof pagesCount === 'number' ? (
          <XPaginationAction
            page={pagesCount}
            disabled={page >= pagesCount}
            label="Go to last page"
            type="last"
            to={to}
            replace={replace}
            onPageChange={onPageChange}
            // className="hidden sm:inline-flex"
          />
        ) : null}
      </PaginationContent>
    </Pagination>
  )
}

export const XPagination = ({
  className,
  to,
  onPageChange: onPageChangeProvided,
  onLimitChange: onLimitChangeProvided,
  onPageOrLimitChange: onPageOrLimitChangeProvided,
  limitOptions,
  replace,
  variant = 'rich',
  // form: _form,
  form,
  ...restProps
}: XPaginationProps) => {
  // const form = _form && fromAnyForm(_form)
  const pagination = useDefined('pagination' in restProps ? restProps.pagination : restProps)
  const {
    page: pageProvided,
    limit: limitProvided,
    total,
    nextPage,
    prevPage,
    pagesCount,
  } = { ...pagination, ...restProps }
  const onPageChange = useMemo(() => {
    return (page: number) => {
      onPageChangeProvided?.(page)
      form?.setValue('page', page)
    }
  }, [onPageChangeProvided, form])
  const onLimitChange = useMemo(() => {
    return (limit: number) => {
      onLimitChangeProvided?.(limit)
      form?.setValue('limit', limit)
    }
  }, [onLimitChangeProvided, form])

  const [_page, _limit] = form
    ? // eslint-disable-next-line react-hooks/rules-of-hooks
      useFValues({ form, name: ['page', 'limit'] })
    : [pageProvided, limitProvided]
  const page = !_page ? 1 : typeof _page === 'number' ? _page : Number(_page)
  const limit = !_limit ? 20 : typeof _limit === 'number' ? _limit : Number(_limit)
  const totalLabel = typeof total === 'number' ? `${total} total` : undefined
  useChanged(() => {
    onPageOrLimitChangeProvided?.(page, limit)
  }, [limit])

  if (total === 0) {
    return null
  }

  return (
    <div
      className={cn(
        'flex flex-wrap items-center justify-center gap-3 py-6 sm:justify-between',
        className,
        !pagination && 'hidden',
      )}
    >
      <div className="flex items-center gap-2 font-accent text-sm text-muted-foreground">
        {totalLabel ? <span>{totalLabel}</span> : null}
        {totalLabel ? <span className="mx-2">/</span> : null}
        <XPaginationLimit className="p-0" limit={limit} onLimitChange={onLimitChange} limitOptions={limitOptions} />
      </div>
      <div className="flex flex-wrap items-center justify-center gap-3">
        {variant === 'rich' ? (
          <>
            <XPaginationPagesRich
              page={page}
              pagesCount={pagesCount}
              prevPage={prevPage}
              nextPage={nextPage}
              to={to}
              replace={replace}
              onPageChange={onPageChange}
              className="hidden sm:flex"
            />
            <XPaginationPagesPoor
              page={page}
              pagesCount={pagesCount}
              prevPage={prevPage}
              nextPage={nextPage}
              to={to}
              replace={replace}
              onPageChange={onPageChange}
              className="sm:hidden"
            />
          </>
        ) : (
          <XPaginationPagesPoor
            page={page}
            pagesCount={pagesCount}
            prevPage={prevPage}
            nextPage={nextPage}
            to={to}
            replace={replace}
            onPageChange={onPageChange}
          />
        )}
      </div>
    </div>
  )
}

type PaginateItem = Record<string, unknown>

// paged

export type PaginatePagedInput<
  TItem extends PaginateItem = PaginateItem,
  TTotal extends number | undefined = number | undefined,
> = {
  items: TItem[]
  limit: number
  page: number
  total?: TTotal
}

export type PaginatePagedOutput<
  TItem extends PaginateItem = PaginateItem,
  TTotal extends number | undefined = number | undefined,
> = {
  /** Items to paginate. Should be one more than the limit if total is not provided */
  items: TItem[]
  pagination: {
    limit: number
    page: number
    nextPage?: number
    prevPage?: number
    pagesCount: TTotal extends number ? number : undefined
    total: TTotal
  }
}

export const paginatePaged = <TItem extends PaginateItem, TTotal extends number | undefined = undefined>({
  items,
  page,
  limit,
  total,
}: PaginatePagedInput<TItem, TTotal>): PaginatePagedOutput<TItem, TTotal> => {
  if (!env.side.is.server) {
    throw new Error('Server Only')
  }
  const offset = (page - 1) * limit
  const nextOffset = offset + limit
  const hasNextPage = total ? nextOffset < total : items.length > limit
  const hasPrevPage = page > 1
  const nextPage = hasNextPage ? page + 1 : undefined
  const prevPage = hasPrevPage ? page - 1 : undefined
  const pagesCount = total ? Math.ceil(total / limit) : undefined
  return {
    items: items.slice(0, limit),
    pagination: {
      page,
      limit,
      total: total as TTotal,
      nextPage,
      prevPage,
      pagesCount: pagesCount as TTotal extends number ? number : undefined,
    },
  }
}

// cursor

export type PaginateCursorInput<
  TItem extends PaginateItem = PaginateItem,
  TCursorKey extends keyof TItem = string,
  TTotal extends number | undefined = number | undefined,
> = {
  items: TItem[]
  limit: number
  cursorKey: TCursorKey
  total?: TTotal
}

export type PaginateCursorOutput<
  TItem extends PaginateItem = PaginateItem,
  TCursorKey extends keyof TItem = string,
  TTotal extends number | undefined = number | undefined,
> = {
  /** Items to paginate. Should be one more than the limit */
  items: TItem[]
  pagination: {
    limit: number
    nextCursor: string extends TCursorKey ? unknown : TItem[TCursorKey] | undefined
    cursorKey: TCursorKey
    total: TTotal
  }
}

export const paginateCursor = <
  TItem extends PaginateItem,
  TCursorKey extends keyof TItem,
  TTotal extends number | undefined = undefined,
>({
  items,
  limit,
  cursorKey,
  total,
}: PaginateCursorInput<TItem, TCursorKey, TTotal>): Prettify<PaginateCursorOutput<TItem, TCursorKey, TTotal>> => {
  if (!env.side.is.server) {
    throw new Error('Server Only')
  }
  const hasNextCursor = items.length > limit
  if (!hasNextCursor) {
    return {
      items,
      pagination: {
        limit,
        cursorKey,
        nextCursor: undefined,
        total: total as TTotal,
      },
    }
  }
  const nextCursor = items.at(-1)?.[cursorKey]
  return {
    items: items.slice(0, limit),
    pagination: {
      limit,
      cursorKey,
      nextCursor,
      total: total as TTotal,
    },
  }
}
