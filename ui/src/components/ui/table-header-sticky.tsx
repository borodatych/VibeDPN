import { cn } from '@/utils'
import * as React from 'react'
import { createPortal } from 'react-dom'

type TableHeaderStickyProps = React.ComponentProps<'thead'> & {
  enabled?: boolean
  offset?: number
}

type StickyHeaderLayout = {
  mode: 'fixed' | 'bottom'
  target: HTMLElement
  columns: number[]
  tableClassName: string
  wrapperStyle: React.CSSProperties
  tableStyle: React.CSSProperties
}

function setRef<T>(ref: React.Ref<T> | undefined, value: T | null) {
  if (typeof ref === 'function') {
    ref(value)
    return
  }

  if (ref) {
    ref.current = value
  }
}

function sameLayout(a: StickyHeaderLayout | null, b: StickyHeaderLayout | null) {
  return (
    a?.mode === b?.mode &&
    a?.target === b?.target &&
    a?.tableClassName === b?.tableClassName &&
    JSON.stringify(a?.columns) === JSON.stringify(b?.columns) &&
    JSON.stringify(a?.wrapperStyle) === JSON.stringify(b?.wrapperStyle) &&
    JSON.stringify(a?.tableStyle) === JSON.stringify(b?.tableStyle)
  )
}

function TableHeaderSticky({
  className,
  enabled = true,
  offset: stickyOffset = 0,
  ref,
  ...props
}: TableHeaderStickyProps) {
  const headerRef = React.useRef<HTMLTableSectionElement | null>(null)
  const [layout, setLayout] = React.useState<StickyHeaderLayout | null>(null)

  const updateLayout = React.useCallback(() => {
    const header = headerRef.current
    const table = header?.closest('[data-slot="table"]')
    const container = header?.closest('[data-slot="table-container"]')

    if (!enabled || !header || !(table instanceof HTMLTableElement) || !(container instanceof HTMLElement)) {
      setLayout(null)
      return
    }

    const headerRect = header.getBoundingClientRect()
    const tableRect = table.getBoundingClientRect()
    const containerRect = container.getBoundingClientRect()
    const headerHeight = headerRect.height

    if (tableRect.top > stickyOffset || headerHeight === 0) {
      setLayout(null)
      return
    }

    const columns = Array.from(header.querySelectorAll('th')).map((cell) =>
      Math.round(cell.getBoundingClientRect().width),
    )
    const tableClassName = table.className

    const next: StickyHeaderLayout =
      tableRect.bottom - headerHeight <= stickyOffset
        ? {
            mode: 'bottom' as const,
            target: container,
            columns,
            tableClassName,
            wrapperStyle: {
              height: headerHeight,
              left: 0,
              overflow: 'hidden',
              position: 'absolute',
              top: table.offsetTop + table.offsetHeight - headerHeight,
              width: container.clientWidth,
              zIndex: 40,
            },
            tableStyle: {
              left: table.offsetLeft - container.scrollLeft,
              position: 'absolute',
              width: tableRect.width,
            },
          }
        : {
            mode: 'fixed' as const,
            target: document.body,
            columns,
            tableClassName,
            wrapperStyle: {
              height: headerHeight,
              left: containerRect.left,
              overflow: 'hidden',
              position: 'fixed',
              top: stickyOffset,
              width: containerRect.width,
              zIndex: 40,
            },
            tableStyle: {
              left: tableRect.left - containerRect.left,
              position: 'absolute',
              width: tableRect.width,
            },
          }

    setLayout((current) => (sameLayout(current, next) ? current : next))
  }, [enabled, stickyOffset])

  React.useLayoutEffect(() => {
    updateLayout()

    if (!enabled) {
      return
    }

    const header = headerRef.current
    const table = header?.closest('[data-slot="table"]')
    const container = header?.closest('[data-slot="table-container"]')

    if (!header || !(table instanceof HTMLTableElement) || !(container instanceof HTMLElement)) {
      return
    }

    const resizeObserver = new ResizeObserver(updateLayout)
    resizeObserver.observe(header)
    resizeObserver.observe(table)
    resizeObserver.observe(container)

    window.addEventListener('scroll', updateLayout, { passive: true })
    window.addEventListener('resize', updateLayout)
    container.addEventListener('scroll', updateLayout, { passive: true })

    return () => {
      resizeObserver.disconnect()
      window.removeEventListener('scroll', updateLayout)
      window.removeEventListener('resize', updateLayout)
      container.removeEventListener('scroll', updateLayout)
    }
  }, [enabled, updateLayout])

  const handleRef = React.useCallback(
    (node: HTMLTableSectionElement | null) => {
      headerRef.current = node
      setRef(ref, node)
    },
    [ref],
  )

  const headerClassName = cn('[&_tr]:border-b', enabled && layout && 'invisible', className)
  const stickyHeader = layout
    ? createPortal(
        <div data-slot="table-sticky-header-container" style={layout.wrapperStyle}>
          <table
            data-slot="table-sticky-header"
            className={cn('bg-background', layout.tableClassName)}
            style={layout.tableStyle}
          >
            <colgroup>
              {layout.columns.map((width, index) => (
                <col key={index} style={{ width }} />
              ))}
            </colgroup>
            <thead
              data-slot="table-header"
              data-sticky-state={layout.mode}
              className={cn('[&_tr]:border-b', className)}
              {...props}
            />
          </table>
        </div>,
        layout.target,
      )
    : null

  return (
    <>
      <thead data-slot="table-header" className={headerClassName} ref={handleRef} {...props} />
      {stickyHeader}
    </>
  )
}

export { TableHeaderSticky }
