/*
---
readme: true
description: ...
apply: ...
---
...
*/

import { XDropdown, type XDropdownItemDef } from '@/components/blocks/dropdown'
import { useDefined } from '@/components/hooks/use-defined'
import { Button, type ButtonIconType } from '@/components/ui/button'
import { useT } from '@/modules/i18n/use-t'
import { Spinner } from '@/components/ui/spinner'
import { Table, TableBody, TableCell, TableHead, TableRow } from '@/components/ui/table'
import { TableHeaderSticky } from '@/components/ui/table-header-sticky'
import { ValueBare, type ValueBareProps, type ValueVariant } from '@/components/ui/value'
import { ErrorComponent } from '@/components/other/error'
import { navigate } from '@/lib/navigation'
import { cn } from '@/utils'
import { toHumanCase } from '@point0/core'
import type { InfiniteData, UseInfiniteQueryResult, UseQueryResult } from '@tanstack/react-query'
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type AccessorFnColumnDef,
  type AccessorKeyColumnDef,
  type ColumnDef,
  type DisplayColumnDef,
  type GroupColumnDef,
  type Row,
  type TableOptions,
} from '@tanstack/react-table'
import { useWindowVirtualizer } from '@tanstack/react-virtual'
import { cva, type VariantProps } from 'class-variance-authority'
import { EllipsisVerticalIcon } from 'lucide-react'
import * as React from 'react'

type XTableValueCellProps = {
  [TVariant in ValueVariant]: Omit<ValueBareProps<TVariant>, 'data'>
}[ValueVariant]

type XTableColumnDefWithValueCell<TColumnDef extends ColumnDef<any>> = Omit<TColumnDef, 'cell'> & {
  cell?: TColumnDef['cell'] | XTableValueCellProps
}

export type XTableColumnDef<TData> =
  | XTableColumnDefWithValueCell<DisplayColumnDef<TData>>
  | XTableColumnDefWithValueCell<GroupColumnDef<TData>>
  | XTableColumnDefWithValueCell<AccessorKeyColumnDef<TData>>
  | XTableColumnDefWithValueCell<AccessorFnColumnDef<TData>>

export type XTableProps<TData> = {
  data?: TData[]
  loading?: boolean
  error?: unknown
  query?: XTableQuery<TData>
  actions?: XTableActionsDef<TData>
  columns?: XTableColumnDef<TData>[]
  empty?: React.ReactNode

  onRowClick?: (row: TData) => void | Promise<void>
  onRowDoubleClick?: (row: TData) => void | Promise<void>
  to?: (row: TData) => ({ to: string } & NonNullable<Parameters<typeof navigate.to>[1]>) | string

  sticky?: boolean
  stickyOffset?: number

  virtualizer?: XTableVirtualizerOptions | true
  isLoadingMore?: boolean
  loadingMore?: React.ReactNode
  canLoadMore?: boolean
  loadMore?: React.ReactNode
  onLoadMore?: () => unknown | Promise<unknown>
  loadMoreOnReachEnd?: boolean

  className?: string
  tableClassName?: string
  headerClassName?: string
  headerRowClassName?: string
  headerCellClassName?: string
  bodyClassName?: string
  rowClassName?: string
  cellClassName?: string
  emptyCellClassName?: string
  actionsClassName?: string
} & VariantProps<typeof appTableWrapperVariants> &
  Omit<Partial<TableOptions<TData>>, 'data' | 'columns' | 'getCoreRowModel'>

export type XTableActionDefOutput = {
  hide?: boolean
  label?: string
  icon?: XTableActionIcon
  tooltip?: string
  destructive?: boolean | string
} & (
  | {
      to?: string
      onClick?: () => void
      dropdown?: undefined
    }
  | {
      dropdown?: XDropdownItemDef[]
      to?: undefined
      onClick?: undefined
    }
)

export type XTableActionsDef<TData> = (data: TData) => XTableActionDefOutput[]

export type XTableVirtualizerOptions = Partial<Parameters<typeof useWindowVirtualizer>[0]>

const appTableWrapperVariants = cva('', {
  variants: {
    variant: {
      bordered: 'overflow-hidden rounded-lg border',
      clean: '',
    },
  },
  defaultVariants: {
    variant: 'clean',
  },
})

const appTableHeaderVariants = cva('', {
  variants: {
    variant: {
      bordered: 'bg-muted/50',
      clean: '',
    },
  },
  defaultVariants: {
    variant: 'clean',
  },
})

const APP_TABLE_CORE_ROW_MODEL = getCoreRowModel()

type XTableActionIcon = ButtonIconType

const XTableActionDropdown = ({
  action,
}: {
  action: Extract<XTableActionDefOutput, { dropdown?: XDropdownItemDef[] }>
}) => {
  return (
    <XDropdown items={action.dropdown} contentProps={{ align: 'end', className: 'w-40' }}>
      <Button
        variant="ghost"
        size="sm"
        title={action.tooltip}
        // className="size-8 p-0"
        children={action.label}
        icon={action.icon || EllipsisVerticalIcon}
      />
    </XDropdown>
  )
}

const XTableActions = <TData,>({
  item,
  actions,
  className,
}: {
  item: TData
  actions: XTableActionsDef<TData>
  className?: string
}) => {
  const visibleActions = actions(item).filter((action) => !action.hide)

  if (!visibleActions.length) {
    return null
  }

  return (
    <div
      className={cn('flex items-center justify-end gap-1', className)}
      onClick={(event) => event.stopPropagation()}
      onDoubleClick={(event) => event.stopPropagation()}
    >
      {visibleActions.map((action, index) => {
        if (action.dropdown) {
          return <XTableActionDropdown key={index} action={action} />
        }

        return (
          <Button
            key={index}
            variant={action.destructive ? 'destructive' : 'ghost'}
            size={'sm'}
            to={action.to}
            onClick={action.onClick}
            hint={action.tooltip}
            confirm={
              action.destructive
                ? typeof action.destructive === 'string'
                  ? action.destructive
                  : 'Are you sure?'
                : undefined
            }
            icon={action.icon}
            children={action.label}
          />
        )
      })}
    </div>
  )
}

const XTableDataRow = <TData,>({
  row,
  virtualIndex,
  measureElement,
  rowClassName,
  cellClassName,
  onRowClick,
  onRowDoubleClick,
  to: getRowLink,
}: {
  row: Row<TData>
  virtualIndex?: number
  measureElement?: (node: HTMLTableRowElement | null) => void
  rowClassName?: string
  cellClassName?: string
  onRowClick?: (row: TData) => void | Promise<void>
  onRowDoubleClick?: (row: TData) => void | Promise<void>
  to?: (row: TData) => ({ to: string } & NonNullable<Parameters<typeof navigate.to>[1]>) | string
}) => {
  const onClickLikeLink = React.useMemo(
    () =>
      !getRowLink
        ? undefined
        : (event?: React.MouseEvent<HTMLTableRowElement>) => {
            const linkRaw = getRowLink(row.original)
            const to = typeof linkRaw === 'string' ? linkRaw : linkRaw.to
            const props = typeof linkRaw === 'string' ? {} : linkRaw
            if (event?.metaKey || event?.ctrlKey) {
              void navigate.to(to, { ...props, newTab: true })
              return
            }
            void navigate.to(to, props)
          },
    [getRowLink, row.original],
  )
  const onRowClickNormalized = React.useMemo(
    () =>
      !onClickLikeLink && !onRowClick
        ? undefined
        : (event: React.MouseEvent<HTMLTableRowElement>) => {
            onClickLikeLink?.(event)
            void onRowClick?.(row.original)
          },
    [onClickLikeLink, onRowClick, row.original],
  )
  return (
    <TableRow
      ref={measureElement}
      data-index={virtualIndex}
      data-state={row.getIsSelected() && 'selected'}
      data-item-row
      className={cn(onRowClickNormalized && 'cursor-pointer', rowClassName)}
      onClick={onRowClickNormalized}
      onDoubleClick={onRowDoubleClick ? () => void onRowDoubleClick(row.original) : undefined}
    >
      {row.getVisibleCells().map((cell) => (
        <TableCell key={cell.id} className={cellClassName}>
          {flexRender(cell.column.columnDef.cell, cell.getContext())}
        </TableCell>
      ))}
    </TableRow>
  )
}

const XTableExtraRow = ({
  colSpan,
  children,
  virtualIndex,
  measureElement,
  cellClassName,
}: {
  colSpan: number
  children: React.ReactNode
  virtualIndex?: number
  measureElement?: (node: HTMLTableRowElement | null) => void
  cellClassName?: string
}) => {
  return (
    <TableRow ref={measureElement} data-index={virtualIndex}>
      <TableCell colSpan={colSpan} className={cn('h-16 text-center text-muted-foreground', cellClassName)}>
        {children}
      </TableCell>
    </TableRow>
  )
}

type XTableQuery<TData> = UseQueryResult<{ items: TData[] }> | UseInfiniteQueryResult<InfiniteData<{ items: TData[] }>>

const getItemsFromQueryData = <TData,>(data: XTableQuery<TData>['data']) => {
  if (!data) {
    return undefined
  }
  if ('items' in data) {
    return data.items
  }
  return data.pages.flatMap((page) => page.items)
}

export const XTable = <TData,>({
  data: dataProvided,
  loading,
  query,
  error,
  actions,
  columns: columnsProvided,
  empty,
  onRowClick,
  onRowDoubleClick,
  to,
  sticky,
  stickyOffset,

  virtualizer: virtualizerOptions,
  isLoadingMore: _isLoadingMore,
  canLoadMore: _canLoadMore,
  onLoadMore: _onLoadMore,
  loadMoreOnReachEnd,
  loadingMore,
  loadMore,

  className,
  tableClassName,
  headerClassName,
  headerRowClassName,
  headerCellClassName,
  bodyClassName,
  rowClassName,
  cellClassName,
  emptyCellClassName,
  actionsClassName,
  variant,
  ...tableOptions
}: XTableProps<TData>) => {
  const t = useT()
  const scrollRef = React.useRef<HTMLDivElement>(null)
  const [hasMounted, setHasMounted] = React.useState(false)
  React.useEffect(() => {
    setHasMounted(true)
  }, [])
  const queryData = query?.data
  const queryItems = React.useMemo(() => getItemsFromQueryData(queryData), [queryData])
  const data = useDefined(dataProvided ?? queryItems, [])
  loading ??= query?.isLoading
  error ??= query?.error

  const columns = React.useMemo<ColumnDef<TData>[]>(() => {
    if (columnsProvided) {
      return columnsProvided.map((column): ColumnDef<TData> => {
        const { cell, ...columnProps } = column
        const valueCellProps = cell && typeof cell === 'object' ? cell : undefined
        const header =
          columnProps.header ??
          ('accessorKey' in columnProps && typeof columnProps.accessorKey === 'string'
            ? toHumanCase(columnProps.accessorKey)
            : undefined)

        return {
          ...columnProps,
          header,
          cell:
            typeof cell === 'function'
              ? cell
              : (context) => <ValueBare {...valueCellProps} data={context.getValue()} />,
        } as ColumnDef<TData>
      })
    }

    return Object.keys(data.at(0) ?? {}).map((key) => ({
      accessorKey: key,
      header: toHumanCase(key),
      cell: (context) => <ValueBare data={context.getValue()} />,
    })) as ColumnDef<TData>[]
  }, [columnsProvided, data])

  const tableColumns = React.useMemo<ColumnDef<TData>[]>(() => {
    if (!actions) {
      return columns
    }

    return [
      ...columns,
      {
        id: 'actions',
        enableHiding: false,
        cell: ({ row }) => <XTableActions item={row.original} actions={actions} className={actionsClassName} />,
        ...columns.find((column) => column.id === 'actions'),
      },
    ]
  }, [actions, actionsClassName, columns])

  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data,
    columns: tableColumns,
    getCoreRowModel: APP_TABLE_CORE_ROW_MODEL,
    ...tableOptions,
  })
  const rows = table.getRowModel().rows
  const colSpan = table.getAllLeafColumns().length

  const shouldVirtualize = !!loadMoreOnReachEnd || !!loadMore || !!virtualizerOptions
  const virtualizeNow = shouldVirtualize && hasMounted
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
  const showExtraRow = isLoadingMore || (manualLoadMore && (canLoadMore ?? true))
  const extraRowContent = isLoadingMore ? (
    (loadingMore ?? t('ui.list.loadingMore'))
  ) : manualLoadMore ? (
    <Button variant="link" type="button" onClick={() => void onLoadMore?.()}>
      {loadMore === true ? t('ui.list.loadMore') : loadMore}
    </Button>
  ) : null
  const virtualRowCount = rows.length + (showExtraRow ? 1 : 0)
  const rowVirtualizer = useWindowVirtualizer({
    overscan: 15,
    enabled: virtualizeNow,
    count: virtualRowCount,
    estimateSize: () => (actions ? 49 : 37),
    ...(typeof virtualizerOptions === 'object' ? virtualizerOptions : {}),
  })
  const virtualRows = rowVirtualizer.getVirtualItems()
  const lastVirtualRowIndex = virtualRows.at(-1)?.index
  const virtualPaddingTop = virtualRows[0]?.start ?? 0
  const virtualPaddingBottom = virtualRows.length ? rowVirtualizer.getTotalSize() - (virtualRows.at(-1)?.end ?? 0) : 0
  React.useEffect(() => {
    if (!virtualizeNow || !loadMoreOnReachEnd || !canLoadMore || !onLoadMore || isLoadingMore || rows.length === 0) {
      return
    }
    if (lastVirtualRowIndex !== undefined && lastVirtualRowIndex >= rows.length - 1) {
      void onLoadMore()
    }
  }, [canLoadMore, isLoadingMore, lastVirtualRowIndex, onLoadMore, rows.length, virtualizeNow, loadMoreOnReachEnd])

  if (error) {
    return (
      <div className={className}>
        <ErrorComponent error={error} />
      </div>
    )
  }

  return (
    <div ref={scrollRef} className={cn('relative max-w-full min-w-0', appTableWrapperVariants({ variant }), className)}>
      <Table className={tableClassName}>
        {rows.length !== 0 && (
          <TableHeaderSticky
            className={cn(appTableHeaderVariants({ variant }), headerClassName)}
            enabled={!!sticky}
            offset={stickyOffset}
          >
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id} className={headerRowClassName}>
                {headerGroup.headers.map((header) => (
                  <TableHead key={header.id} colSpan={header.colSpan} className={headerCellClassName}>
                    {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeaderSticky>
        )}
        <TableBody className={cn(loading && 'opacity-50', 'transition-opacity', bodyClassName)}>
          {rows.length === 0 && loading ? (
            <TableRow>
              <TableCell colSpan={colSpan} className={cn('h-24 text-center', emptyCellClassName)}>
                <Spinner size="xl" className="mx-auto text-muted-foreground" />
              </TableCell>
            </TableRow>
          ) : rows.length === 0 ? (
            <TableRow>
              <TableCell colSpan={colSpan} className={cn('h-24 text-center text-muted-foreground', emptyCellClassName)}>
                {empty ?? t('ui.list.noResults')}
              </TableCell>
            </TableRow>
          ) : virtualizeNow ? (
            <>
              {virtualPaddingTop > 0 ? (
                <TableRow aria-hidden="true">
                  <TableCell colSpan={colSpan} className="p-0" style={{ height: virtualPaddingTop }} />
                </TableRow>
              ) : null}
              {virtualRows.map((virtualRow) => {
                if (virtualRow.index >= rows.length) {
                  return (
                    <XTableExtraRow
                      key="extra-row"
                      colSpan={colSpan}
                      virtualIndex={virtualRow.index}
                      measureElement={rowVirtualizer.measureElement}
                      cellClassName={cellClassName}
                    >
                      {extraRowContent}
                    </XTableExtraRow>
                  )
                }

                const row = rows[virtualRow.index]

                return (
                  <XTableDataRow
                    key={row.id}
                    row={row}
                    to={to}
                    virtualIndex={virtualRow.index}
                    measureElement={rowVirtualizer.measureElement}
                    rowClassName={cn(rowClassName)}
                    cellClassName={cellClassName}
                    onRowClick={onRowClick}
                    onRowDoubleClick={onRowDoubleClick}
                  />
                )
              })}
              {virtualPaddingBottom > 0 ? (
                <TableRow aria-hidden="true">
                  <TableCell colSpan={colSpan} className="p-0" style={{ height: virtualPaddingBottom }} />
                </TableRow>
              ) : null}
            </>
          ) : (
            <>
              {rows.map((row) => (
                <XTableDataRow
                  key={row.id}
                  row={row}
                  to={to}
                  rowClassName={cn(rowClassName)}
                  cellClassName={cellClassName}
                  onRowClick={onRowClick}
                  onRowDoubleClick={onRowDoubleClick}
                />
              ))}
              {showExtraRow ? (
                <XTableExtraRow colSpan={colSpan} cellClassName={cellClassName}>
                  {extraRowContent}
                </XTableExtraRow>
              ) : null}
            </>
          )}
        </TableBody>
      </Table>
      <div
        aria-hidden={!(loading && rows.length > 0)}
        className={cn(
          'pointer-events-none absolute inset-x-0 top-10 bottom-0 grid place-items-center opacity-0 transition-opacity',
          loading && rows.length > 0 && 'opacity-100',
        )}
      >
        <Spinner size="2xl" className="text-muted-foreground" />
      </div>
    </div>
  )
}
