import { useBreakpoint } from '@/components/hooks/use-breakpoint'
import { Button } from '@/components/ui/button'
import { cn } from '@/utils'
import { PlusIcon } from 'lucide-react'
import type { ReactNode } from 'react'

/** A line of the list: what it is called, and a mark beside the name (a state, a count) */
export type ListDetailItem = { key: string; title: string; aside?: ReactNode }

/**
 * A list on the left and the item it opens on the right, two thirds of the width («Exits», «Rules»)
 * On a phone the item opens under its own line of the list, not in a second column below the whole list
 *
 * The key of the open item lives in the URL of the page, so the caller owns it: `picked` and `onPick`
 * `add` is the last line of the list, a button that opens its own item (a form adding one more)
 *
 * @tags ui
 */
export const ListDetail = ({
  label,
  items,
  picked,
  onPick,
  add,
  detail,
}: {
  /** the name of the list for the reader of the screen */
  label: string
  items: ListDetailItem[]
  picked: string
  onPick: (key: string) => void
  add?: { key: string; label: string }
  detail: ReactNode
}) => {
  const phone = useBreakpoint('max-lg')
  return (
    <div className="grid items-start gap-6 lg:grid-cols-3">
      <nav aria-label={label} className="flex min-w-0 flex-col gap-2">
        {items.map((item) => (
          <div key={item.key} className="flex flex-col gap-4">
            <button
              type="button"
              data-item={item.key}
              aria-current={item.key === picked || undefined}
              className={cn(
                'flex w-full items-center justify-between gap-3 rounded-lg border border-border px-4 py-3 text-left transition-colors hover:bg-muted',
                item.key === picked && 'border-primary bg-muted',
              )}
              onClick={() => onPick(item.key)}
            >
              <span className="min-w-0 font-accent text-sm font-semibold">{item.title}</span>
              {item.aside}
            </button>
            {phone && item.key === picked && detail}
          </div>
        ))}
        {add && (
          <div className="flex flex-col gap-4">
            <Button
              variant={picked === add.key ? 'default' : 'outline-secondary'}
              icon={PlusIcon}
              onClick={() => onPick(add.key)}
            >
              {add.label}
            </Button>
            {phone && picked === add.key && detail}
          </div>
        )}
      </nav>
      {!phone && <div className="min-w-0 lg:col-span-2">{detail}</div>}
    </div>
  )
}
