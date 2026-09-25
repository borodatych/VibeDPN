import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { ErrorComponent } from '@/components/other/error'
import { useT } from '@/modules/i18n/use-t'
import { cn } from '@/utils'
import type { InfiniteData, UseInfiniteQueryResult, UseQueryResult } from '@tanstack/react-query'
import { useWindowVirtualizer } from '@tanstack/react-virtual'
import { Slot } from 'radix-ui'
import * as React from 'react'

export type InfiniteScrollQuery<TData> =
  UseQueryResult<{ items: TData[] }> | UseInfiniteQueryResult<InfiniteData<{ items: TData[] }>>

export type InfiniteScrollVirtualizerOptions = Partial<Parameters<typeof useWindowVirtualizer>[0]>

export type InfiniteScrollLoadMoreState = {
  onLoadMore?: () => unknown | Promise<unknown>
  canLoadMore?: boolean
  isLoadingMore?: boolean
}

export type InfiniteScrollLoadMore = React.ReactNode | true | ((state: InfiniteScrollLoadMoreState) => React.ReactNode)

export type InfiniteScrollProps<TData> = {
  data?: TData[]
  query?: InfiniteScrollQuery<TData>
  loading?: boolean
  error?: unknown
  empty?: React.ReactNode

  getItemKey?: (item: TData, index: number) => React.Key

  as?: React.ElementType
  itemAs?: React.ElementType
  extraItemAs?: React.ElementType

  virtualizer?: InfiniteScrollVirtualizerOptions | true
  isLoadingMore?: boolean
  loadingMore?: React.ReactNode
  canLoadMore?: boolean
  loadMore?: InfiniteScrollLoadMore
  onLoadMore?: () => unknown | Promise<unknown>
  loadMoreOnReachEnd?: boolean

  className?: string
  listClassName?: string
  itemClassName?: string
  emptyClassName?: string
  loadingClassName?: string
  loadingMoreClassName?: string
  loadMoreClassName?: string
} & (
  | {
      renderItem: (item: TData, index: number) => React.ReactNode
      children?: undefined
    }
  | {
      renderItem?: undefined
      children: (item: TData, index: number) => React.ReactNode
    }
)

const getItemsFromQueryData = <TData,>(data: InfiniteScrollQuery<TData>['data']) => {
  if (!data) {
    return undefined
  }
  if ('items' in data) {
    return data.items
  }
  return data.pages.flatMap((page) => page.items)
}

const subscribeToMount = () => () => {}
const getClientSnapshot = () => true
const getServerSnapshot = () => false

const renderLoadMore = (
  loadMore: InfiniteScrollLoadMore,
  state: InfiniteScrollLoadMoreState,
  label: string,
): React.ReactNode => {
  if (typeof loadMore === 'function') {
    return loadMore(state)
  }

  return (
    <Button variant="link" type="button" onClick={() => void state.onLoadMore?.()}>
      {loadMore === true ? label : loadMore}
    </Button>
  )
}

export const InfiniteScroll = <TData,>({
  data: dataProvided,
  query,
  loading,
  error,
  empty,
  getItemKey,
  as: List = 'div',
  itemAs: ItemWrapper,
  extraItemAs: ExtraItemWrapper = 'div',

  virtualizer: virtualizerOptions,
  isLoadingMore: _isLoadingMore,
  canLoadMore: _canLoadMore,
  onLoadMore: _onLoadMore,
  loadMoreOnReachEnd,
  loadingMore,
  loadMore,

  className,
  listClassName,
  itemClassName,
  emptyClassName,
  loadingClassName,
  loadingMoreClassName,
  loadMoreClassName,

  ...rest
}: InfiniteScrollProps<TData>) => {
  const t = useT()
  const renderItem = rest.renderItem ?? rest.children
  const Item = ItemWrapper || Slot.Root
  const hasMounted = React.useSyncExternalStore(subscribeToMount, getClientSnapshot, getServerSnapshot)

  const queryItems = React.useMemo(() => getItemsFromQueryData(query?.data), [query?.data])
  const data = dataProvided ?? queryItems ?? []
  loading ??= query?.isLoading
  error ??= query?.error

  const { onLoadMore, canLoadMore, isLoadingMore } = React.useMemo(() => {
    if (_onLoadMore || (!loadMoreOnReachEnd && !loadMore) || !query || !('fetchNextPage' in query)) {
      return { onLoadMore: _onLoadMore, canLoadMore: _canLoadMore, isLoadingMore: _isLoadingMore }
    }
    return {
      onLoadMore: async () => await query.fetchNextPage(),
      canLoadMore: query.hasNextPage,
      isLoadingMore: query.isFetchingNextPage,
    }
  }, [_onLoadMore, _canLoadMore, _isLoadingMore, loadMoreOnReachEnd, loadMore, query])

  const manualLoadMore = !!loadMore && !loadMoreOnReachEnd
  const showExtraItem = !!isLoadingMore || (manualLoadMore && (canLoadMore ?? true))
  const extraItemContent = isLoadingMore
    ? (loadingMore ?? t('ui.list.loadingMore'))
    : manualLoadMore
      ? renderLoadMore(loadMore, { onLoadMore, canLoadMore, isLoadingMore }, t('ui.list.loadMore'))
      : null

  const shouldVirtualize = !!loadMoreOnReachEnd || !!virtualizerOptions
  const virtualizeNow = shouldVirtualize && hasMounted
  const virtualItemCount = data.length + (showExtraItem ? 1 : 0)
  const virtualizer = useWindowVirtualizer({
    overscan: 10,
    enabled: virtualizeNow,
    count: virtualItemCount,
    estimateSize: () => 120,
    ...(typeof virtualizerOptions === 'object' ? virtualizerOptions : {}),
  })
  const virtualItems = virtualizer.getVirtualItems()
  const lastVirtualItemIndex = virtualItems.at(-1)?.index
  const virtualPaddingTop = virtualItems[0]?.start ?? 0
  const virtualPaddingBottom = virtualItems.length ? virtualizer.getTotalSize() - (virtualItems.at(-1)?.end ?? 0) : 0

  React.useEffect(() => {
    if (!virtualizeNow || !loadMoreOnReachEnd || !canLoadMore || !onLoadMore || isLoadingMore || data.length === 0) {
      return
    }
    if (lastVirtualItemIndex !== undefined && lastVirtualItemIndex >= data.length - 1) {
      void onLoadMore()
    }
  }, [canLoadMore, data.length, isLoadingMore, lastVirtualItemIndex, loadMoreOnReachEnd, onLoadMore, virtualizeNow])

  if (error) {
    return (
      <div className={className}>
        <ErrorComponent error={error} />
      </div>
    )
  }

  const renderExtraItem = (props?: { ref?: (node: Element | null) => void; index?: number }) => {
    return (
      <ExtraItemWrapper
        key="extra-item"
        ref={props?.ref}
        data-index={props?.index}
        className={cn('flex min-h-16 items-center justify-center', loadingMoreClassName, loadMoreClassName)}
      >
        {extraItemContent}
      </ExtraItemWrapper>
    )
  }

  const renderDataItem = (item: TData, index: number, ref?: (node: Element | null) => void) => {
    return (
      <Item key={getItemKey?.(item, index) ?? index} ref={ref} data-index={index} className={itemClassName}>
        {renderItem(item, index)}
      </Item>
    )
  }

  const children =
    data.length === 0 && loading ? (
      <div className={cn('flex min-h-24 items-center justify-center', loadingClassName)}>
        <Spinner size="xl" className="text-muted-foreground" />
      </div>
    ) : data.length === 0 ? (
      <div className={cn('min-h-24 content-center text-center text-muted-foreground', emptyClassName)}>
        {empty ?? t('ui.list.noResults')}
      </div>
    ) : virtualizeNow ? (
      <>
        {virtualPaddingTop > 0 ? <div aria-hidden style={{ height: virtualPaddingTop }} /> : null}
        {virtualItems.map((virtualItem) => {
          if (virtualItem.index >= data.length) {
            return renderExtraItem({ ref: virtualizer.measureElement, index: virtualItem.index })
          }

          return renderDataItem(data[virtualItem.index], virtualItem.index, virtualizer.measureElement)
        })}
        {virtualPaddingBottom > 0 ? <div aria-hidden style={{ height: virtualPaddingBottom }} /> : null}
      </>
    ) : (
      <>
        {data.map((item, index) => renderDataItem(item, index))}
        {showExtraItem ? renderExtraItem() : null}
      </>
    )

  return (
    <div className={cn('relative max-w-full min-w-0', className)}>
      <List className={cn(loading && data.length > 0 && 'opacity-50', 'transition-opacity', listClassName)}>
        {children}
      </List>
    </div>
  )
}
