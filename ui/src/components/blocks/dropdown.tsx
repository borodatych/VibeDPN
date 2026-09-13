/**
 * XDropdown — a dropdown menu built on the Shadcn `DropdownMenu` (`@/components/ui/dropdown-menu`). Use it for the
 * common case; reach for `DropdownMenu` directly only when you need functionality it doesn't cover.
 *
 * @example
 *   ;<XDropdown
 *     items={[
 *       { label: 'Item 1', to: '/item1' },
 *       { label: 'Item 2', to: '/item2' },
 *     ]}
 *   />
 *
 * @id x-dropdown
 * @tags rule, blocks
 */

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Icon, type IconType } from '@/components/ui/icon'
import { Link } from '@/lib/navigation'
import { cn } from '@/utils'
import * as React from 'react'

export type XDropdownItemDef =
  | {
      key?: React.Key
      hide?: boolean
      label: React.ReactNode
      to?: string
      onClick?: () => void
      icon?: IconType
      variant?: 'default' | 'destructive'
      disabled?: boolean
      className?: string
    }
  | '-'

export type XDropdownProps = React.ComponentProps<typeof DropdownMenu> & {
  children: React.ReactNode
  items?: XDropdownItemDef[]
  contentProps?: Omit<React.ComponentProps<typeof DropdownMenuContent>, 'children'>
  itemClassName?: string
  iconClassName?: string
  separatorClassName?: string
}

export const XDropdown = ({
  children,
  items,
  contentProps,
  itemClassName,
  iconClassName = 'size-4',
  separatorClassName,
  modal = false,
  ...props
}: XDropdownProps) => {
  const visibleItems = items?.filter((item) => item === '-' || !item.hide)

  if (!visibleItems?.length) {
    return null
  }

  return (
    <DropdownMenu modal={modal} {...props}>
      <DropdownMenuTrigger asChild>{children}</DropdownMenuTrigger>
      <DropdownMenuContent {...contentProps}>
        {visibleItems.map((item, index) => {
          if (item === '-') {
            return <DropdownMenuSeparator key={index} className={separatorClassName} />
          }

          const content = (
            <>
              <Icon icon={item.icon} className={iconClassName} />
              <span>{item.label}</span>
            </>
          )

          if (item.to) {
            return (
              <DropdownMenuItem
                key={item.key ?? index}
                asChild
                variant={item.variant}
                disabled={item.disabled}
                className={cn(itemClassName, item.className)}
              >
                <Link to={item.to}>{content}</Link>
              </DropdownMenuItem>
            )
          }

          return (
            <DropdownMenuItem
              key={item.key ?? index}
              variant={item.variant}
              disabled={item.disabled}
              className={cn(itemClassName, item.className)}
              onSelect={() => item.onClick?.()}
            >
              {content}
            </DropdownMenuItem>
          )
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
