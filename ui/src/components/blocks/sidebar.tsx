import { useIsMobile } from '@/components/hooks/use-mobile'
import { XDropdown, type XDropdownItemDef } from '@/components/blocks/dropdown'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
} from '@/components/ui/sidebar'
import { Icon, type IconType } from '@/components/ui/icon'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/utils'
import { Link } from '@/lib/navigation'
import { useLocation } from '@point0/core/navigation'
import { ChevronRightIcon, Ellipsis } from 'lucide-react'
import * as React from 'react'

export type XSidebarProps = {
  sections: Array<XSidebarSectionProps>
}

export type XSidebarSectionProps = {
  label?: React.ReactNode
  hide?: boolean
  items: Array<XSidebarSectionItemDef>
}

export type XSidebarSectionItemDef = {
  label: React.ReactNode
  hide?: boolean
  to?: string
  onClick?: () => void
  icon?: IconType
  tooltip?: string
} & (
  | { collapsible?: Array<XSidebarSectionSubItemDef>; dropdown?: undefined; extra?: undefined; items?: undefined }
  | {
      dropdown?: Array<XSidebarSectionDropdownItemDef>
      collapsible?: undefined
      extra?: undefined
      items?: undefined
    }
  | { extra?: XSidebarSectionItemExtraDef; collapsible?: undefined; dropdown?: undefined; items?: undefined }
  | {
      items?: Array<XSidebarSectionSubItemDef>
      dropdown?: Array<XSidebarSectionDropdownItemDef>
      collapsible?: undefined
      extra?: undefined
    }
  | {
      items?: Array<XSidebarSectionSubItemDef>
      dropdown?: undefined
      collapsible?: undefined
      extra?: XSidebarSectionItemExtraDef
    }
)

export type XSidebarSectionSubItemDef = {
  hide?: boolean
  label: React.ReactNode
  to?: string
  onClick?: () => void
  icon?: IconType
} & (
  | { dropdown?: Array<XSidebarSectionDropdownItemDef>; extra?: undefined }
  | { extra?: XSidebarSectionItemExtraDef; dropdown?: undefined }
)

export type XSidebarSectionDropdownItemDef = XDropdownItemDef

export type XSidebarSectionItemExtraDef = {
  hide?: boolean
  icon?: IconType
  to?: string
  onClick?: () => void
  tooltip?: string
}

const getNestedTos = (item: XSidebarSectionItemDef): string[] => {
  const result: string[] = []
  if (item.to) {
    result.push(item.to)
  }
  if (item.collapsible) {
    item.collapsible.forEach((subItem) => {
      result.push(...getNestedTos(subItem))
    })
  }
  return result
}

const XSidebarSubItemButton = ({ item, pathname }: { item: XSidebarSectionSubItemDef; pathname: string }) => {
  if (item.to) {
    return (
      <SidebarMenuSubButton asChild isActive={item.to === pathname}>
        <Link to={item.to}>
          <Icon icon={item.icon} />
          <span>{item.label}</span>
        </Link>
      </SidebarMenuSubButton>
    )
  }

  return (
    <SidebarMenuSubButton onClick={item.onClick}>
      <Icon icon={item.icon} />
      <span>{item.label}</span>
    </SidebarMenuSubButton>
  )
}

const XSidebarItemButton = ({ item, pathname }: { item: XSidebarSectionItemDef; pathname: string }) => {
  if (item.to) {
    return (
      <SidebarMenuButton asChild isActive={item.to === pathname} tooltip={item.tooltip}>
        <Link to={item.to}>
          <Icon icon={item.icon} />
          <span>{item.label}</span>
        </Link>
      </SidebarMenuButton>
    )
  }

  return (
    <SidebarMenuButton tooltip={item.tooltip} onClick={item.onClick}>
      <Icon icon={item.icon} />
      <span>{item.label}</span>
    </SidebarMenuButton>
  )
}

const XSidebarExtraAction = ({ extra, isSubItem }: { extra: XSidebarSectionItemExtraDef; isSubItem: boolean }) => {
  const action = extra.to ? (
    <SidebarMenuAction asChild>
      <Link to={extra.to} className={cn(isSubItem && '-mt-2')}>
        <Icon icon={extra.icon} />
        <span className="sr-only">{extra.tooltip ?? 'Open action'}</span>
      </Link>
    </SidebarMenuAction>
  ) : (
    <SidebarMenuAction onClick={extra.onClick} className={cn(isSubItem && '-mt-2')}>
      <Icon icon={extra.icon} />
      <span className="sr-only">{extra.tooltip ?? 'Open action'}</span>
    </SidebarMenuAction>
  )

  if (!extra.tooltip) {
    return action
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>{action}</TooltipTrigger>
      <TooltipContent side="right" align="center">
        {extra.tooltip}
      </TooltipContent>
    </Tooltip>
  )
}

const XSidebarDropdownAction = ({
  dropdown,
  isSubItem,
  isMobile,
}: {
  dropdown: Array<XSidebarSectionDropdownItemDef>
  isSubItem: boolean
  isMobile: boolean
}) => (
  <XDropdown
    items={dropdown}
    contentProps={{
      className: 'w-36 rounded-lg',
      side: isMobile ? 'bottom' : 'right',
      align: isMobile ? 'end' : 'start',
    }}
  >
    <SidebarMenuAction className={cn('rounded-sm data-[state=open]:bg-accent', isSubItem && '-mt-2')}>
      <Icon icon={Ellipsis} />
      <span className="sr-only">More</span>
    </SidebarMenuAction>
  </XDropdown>
)

const XSidebarSubItem = ({
  item,
  pathname,
  isMobile,
}: {
  item: XSidebarSectionSubItemDef
  pathname: string
  isMobile: boolean
}) => {
  const dropdown = item.dropdown?.filter((dropdownItem) => dropdownItem === '-' || !dropdownItem.hide)
  const extra = item.extra?.hide ? undefined : item.extra
  return (
    <SidebarMenuSubItem>
      <XSidebarSubItemButton item={item} pathname={pathname} />
      {!!dropdown?.length && <XSidebarDropdownAction dropdown={dropdown} isSubItem={true} isMobile={isMobile} />}
      {!!extra && <XSidebarExtraAction extra={extra} isSubItem={true} />}
    </SidebarMenuSubItem>
  )
}

const XSidebarItem = ({
  item,
  pathname,
  isMobile,
  level,
}: {
  item: XSidebarSectionItemDef
  pathname: string
  isMobile: boolean
  level: number
}) => {
  const collapsible = item.collapsible?.filter((collapsibleItem) => !collapsibleItem.hide)
  if (collapsible?.length) {
    const nestedDropdownTos = getNestedTos(item)
    return (
      <Collapsible
        asChild
        defaultOpen={nestedDropdownTos.includes(pathname)}
        className={cn(
          level === 0 && 'group/collapsible',
          level === 1 && 'group/collapsible-1',
          level === 2 && 'group/collapsible-2',
          level === 3 && 'group/collapsible-3',
        )}
      >
        <SidebarMenuItem>
          <CollapsibleTrigger asChild>
            <SidebarMenuButton tooltip={item.tooltip}>
              <Icon icon={item.icon} />
              <span>{item.label}</span>
              <Icon
                icon={ChevronRightIcon}
                className={cn(
                  'ml-auto transition-transform duration-200',
                  level === 0 && 'group-data-[state=open]/collapsible:rotate-90',
                  level === 1 && 'group-data-[state=open]/collapsible-1:rotate-90',
                  level === 2 && 'group-data-[state=open]/collapsible-2:rotate-90',
                  level === 3 && 'group-data-[state=open]/collapsible-3:rotate-90',
                )}
              />
            </SidebarMenuButton>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <SidebarMenuSub>
              {collapsible.map((subItem, index) => (
                <XSidebarSubItem key={index} item={subItem} pathname={pathname} isMobile={isMobile} />
              ))}
            </SidebarMenuSub>
          </CollapsibleContent>
        </SidebarMenuItem>
      </Collapsible>
    )
  }

  const dropdown = item.dropdown?.filter((dropdownItem) => dropdownItem === '-' || !dropdownItem.hide)
  const items = item.items?.filter((subItem) => !subItem.hide)
  const extra = item.extra?.hide ? undefined : item.extra

  return (
    <SidebarMenuItem>
      <XSidebarItemButton item={item} pathname={pathname} />
      {!!dropdown?.length && <XSidebarDropdownAction dropdown={dropdown} isSubItem={false} isMobile={isMobile} />}
      {!!extra && <XSidebarExtraAction extra={extra} isSubItem={false} />}
      {!!items?.length && (
        <SidebarMenuSub>
          {items.map((subItem, index) => (
            <XSidebarSubItem key={index} item={subItem} pathname={pathname} isMobile={isMobile} />
          ))}
        </SidebarMenuSub>
      )}
    </SidebarMenuItem>
  )
}

export const XSidebarSection = (props: XSidebarSectionProps) => {
  const isMobile = useIsMobile()
  const location = useLocation()

  const items = props.items.filter((item) => !item.hide)

  return (
    <SidebarGroup>
      {props.label && <SidebarGroupLabel>{props.label}</SidebarGroupLabel>}
      <SidebarGroupContent>
        <SidebarMenu>
          {items.map((item, index) => (
            <XSidebarItem key={index} item={item} pathname={location.pathname} isMobile={isMobile} level={0} />
          ))}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  )
}

export const XSidebar = (props: XSidebarProps) => {
  const sections = props.sections.filter((section) => !section.hide)
  return (
    <>
      {sections.map((sectionProps, index) => (
        <XSidebarSection {...sectionProps} key={index} />
      ))}
    </>
  )
}
