import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb'
import { Link } from '@/lib/navigation'
import type { AnyRoute } from '@1gr14/route0'
import { useEffectSsr } from '@point0/core'
import { SsrStore } from '@point0/core/ssr-store'
import { Fragment } from 'react'
import stringify from 'safe-stable-stringify'

export type BreadcrumbItemLabel = string | number
export type BreadcrumbItemTo = string
export type BreadcrumbItem = [BreadcrumbItemLabel, BreadcrumbItemTo] | [BreadcrumbItemLabel] | BreadcrumbItemLabel

export const parseBreadcrumbItem = (item: BreadcrumbItem) => {
  if (typeof item === 'string' || typeof item === 'number') {
    return { label: item, to: undefined }
  }
  return { label: item[0], to: item[1] }
}

export const $breadcrumb = SsrStore.define<BreadcrumbItem[]>('breadcrumb', () => [])

export const useBreadcrumb = (...items: BreadcrumbItem[]) => {
  useEffectSsr(() => {
    $breadcrumb.set(items)
    return () => $breadcrumb.set([])
  }, [stringify(items)])
}

export type XBreadcrumbRoute = {
  label: string
  route: AnyRoute
}

export const XBreadcrumb = ({ items: providedItems }: { items?: Array<[string, string] | string> }) => {
  const storeItems = $breadcrumb.use()
  const items = providedItems ?? storeItems

  return (
    <Breadcrumb>
      <BreadcrumbList>
        {items.map((item, index) => {
          const isLast = index === items.length - 1
          const { label, to } = parseBreadcrumbItem(item)
          if (isLast) {
            if (to) {
              return (
                <BreadcrumbItem key={index}>
                  <BreadcrumbLink asChild>
                    <Link to={to}>{label}</Link>
                  </BreadcrumbLink>
                </BreadcrumbItem>
              )
            }
            return (
              <BreadcrumbItem key={index}>
                <BreadcrumbPage>{label}</BreadcrumbPage>
              </BreadcrumbItem>
            )
          }
          if (to) {
            return (
              <Fragment key={index}>
                <BreadcrumbItem className="hidden md:block">
                  <BreadcrumbLink asChild>
                    <Link to={to}>{label}</Link>
                  </BreadcrumbLink>
                </BreadcrumbItem>
                <BreadcrumbSeparator className="hidden md:block" />
              </Fragment>
            )
          }
          return (
            <Fragment key={index}>
              <BreadcrumbItem className="hidden md:block">{label}</BreadcrumbItem>
              <BreadcrumbSeparator className="hidden md:block" />
            </Fragment>
          )
        })}
      </BreadcrumbList>
    </Breadcrumb>
  )
}
