import { Badge, type BadgeVariant } from '@/components/ui/badge'
import { XInput } from '@/components/ui/input-group'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { Link, type AppLinkProps } from '@/lib/navigation'
import { cn } from '@/utils'
import type { FormatDateVariant } from '@/utils/date'
import { formatDate, isDateCanBeRealtive } from '@/utils/date'
import { fuzzyScore } from '@/utils/fuzzy'
import { formatMoney } from '@/utils/money'
import { env, toHumanCase } from '@point0/core'
import { SearchIcon } from 'lucide-react'
import type { ComponentProps } from 'react'
import React, { useEffect, useReducer } from 'react'

type UsualReactNode = Exclude<React.ReactNode, Promise<any>>

const defaultEmpty: UsualReactNode = (
  <Badge variant="secondary" className="text-muted-foreground opacity-50">
    empty
  </Badge>
)
const defaultNegative: UsualReactNode = <Badge variant="destructive">no</Badge>
const defaultPositive: UsualReactNode = <Badge variant="success">yes</Badge>
const defaultUnknown: UsualReactNode = <Badge variant="warning">unknown</Badge>

type ValuePropsByVariant = {
  any: React.ComponentProps<typeof ValueAny>
  string: React.ComponentProps<typeof ValueString>
  number: React.ComponentProps<typeof ValueNumber>
  boolean: React.ComponentProps<typeof ValueBoolean>
  date: React.ComponentProps<typeof ValueDate>
  badge: React.ComponentProps<typeof ValueBadge>
  element: React.ComponentProps<typeof ValueElement>
  unknown: React.ComponentProps<typeof ValueUnknown>
  money: React.ComponentProps<typeof ValueMoney>
}

export type ValueVariant = keyof ValuePropsByVariant
export type ValueProps<TVariant extends ValueVariant> = ValuePropsByVariant[TVariant]

const mappedHumanized = ({
  data,
  map,
  humanize,
}: {
  data: string
  map?: Record<string, unknown>
  humanize?: boolean
}): UsualReactNode | string => {
  const mapped = map?.[data] ?? data
  if (!humanize || typeof mapped !== 'string') {
    return mapped as UsualReactNode
  }
  return toHumanCase(mapped)
}

export const ValueAny = ({
  data,
  empty = defaultEmpty,
  unknown,
  negative,
  positive,
  dateVariant,
  badgeVariant,
  humanize,
  map,
  link,
}: {
  data: unknown
  empty?: UsualReactNode
  unknown?: UsualReactNode
  negative?: UsualReactNode
  positive?: UsualReactNode
  dateVariant?: FormatDateVariant
  badgeVariant?: BadgeVariant
  humanize?: boolean
  map?: Record<string, unknown>
  link?: string | (AppLinkProps & { target?: ComponentProps<'a'>['target'] })
}) => {
  if (data === undefined || data === null) {
    return empty
  }
  const isArray = Array.isArray(data)
  if (isArray && data.length === 0) {
    return empty
  }
  if (typeof data === 'string') {
    return <ValueString data={data} empty={empty} map={map} humanize={humanize} link={link} />
  }
  if (typeof data === 'number') {
    return <ValueNumber data={data} empty={empty} />
  }
  if (typeof data === 'boolean') {
    return <ValueBoolean data={data} empty={empty} negative={negative} positive={positive} />
  }
  if (data instanceof Date) {
    return <ValueDate data={data} empty={empty} format={dateVariant} />
  }
  if (isArray && data.every((item) => typeof item === 'string')) {
    return <ValueBadge data={data} empty={empty} badge={badgeVariant} map={map} humanize={humanize} />
  }
  if (React.isValidElement(data)) {
    return <ValueElement data={data} empty={empty} />
  }
  return <ValueUnknown data={data} empty={empty} unknown={unknown} />
}

export const ValueString = <TData extends string | undefined | null>({
  data,
  empty = defaultEmpty,
  map,
  humanize,
  link,
}: {
  data: TData
  empty?: UsualReactNode
  map?: Record<Extract<TData, string>, unknown>
  humanize?: boolean
  link?: string | (AppLinkProps & { target?: ComponentProps<'a'>['target'] })
}) => {
  if (!data) {
    return empty
  }
  const mapped = mappedHumanized({ data, map, humanize })
  if (!link) {
    return mapped
  }
  const linkProps = typeof link === 'string' ? { href: link } : link
  return (
    <Link {...linkProps} className="link">
      {mapped}
    </Link>
  )
}

export const ValueNumber = ({ data, empty }: { data: number | undefined | null; empty?: UsualReactNode }) => {
  return data === undefined || data === null ? empty : data
}

export const ValueBoolean = ({
  data,
  empty = defaultEmpty,
  negative = defaultNegative,
  positive = defaultPositive,
}: {
  data: boolean | undefined | null
  empty?: UsualReactNode
  negative?: UsualReactNode
  positive?: UsualReactNode
}) => {
  return data === undefined || data === null ? empty : data ? positive : negative
}

const useRerenderWhileDateCanBeRelative = (date: Date | undefined | null, format: FormatDateVariant): void => {
  const [, rerender] = useReducer((count: number) => count + 1, 0)
  useEffect(() => {
    const canRenderRelative = format === 'relative' || format === 'date-nice' || format === 'date-time-nice'
    if (!date || !canRenderRelative || !isDateCanBeRealtive(date)) {
      return
    }
    const intervalId = setInterval(() => {
      if (!isDateCanBeRealtive(date)) {
        clearInterval(intervalId)
        return
      }
      rerender()
    }, 60_000)
    return () => clearInterval(intervalId)
  }, [date, format])
}

export const ValueDate = ({
  data,
  empty,
  format = 'date-time-nice',
}: {
  data: Date | undefined | null
  empty?: UsualReactNode
  format?: FormatDateVariant
}) => {
  useRerenderWhileDateCanBeRelative(data, format)
  return data === undefined || data === null ? empty : formatDate(data, format)
}

export const ValueBadge = <TData extends string>({
  data,
  empty = defaultEmpty,
  badge = 'secondary',
  map,
  humanize,
}: {
  data: TData[] | TData | undefined | null
  empty?: UsualReactNode
  map?: Record<TData, unknown>
  badge?: BadgeVariant | Record<TData, BadgeVariant> | ((data: TData) => BadgeVariant)
  humanize?: boolean
}) => {
  const items = (Array.isArray(data) ? data : [data]).filter(Boolean) as TData[]
  if (!items.length) {
    return empty
  }
  const renderItem = (item: TData) => {
    const value = mappedHumanized({ data: item, map, humanize })
    const badgeVariant = !badge
      ? badge
      : typeof badge === 'string'
        ? badge
        : typeof badge === 'function'
          ? badge(item)
          : badge[item]
    return (
      <Badge key={item} variant={badgeVariant}>
        {value}
      </Badge>
    )
  }
  if (items.length === 1) {
    return renderItem(items[0])
  }
  return <div className="flex flex-row flex-wrap gap-x-8 gap-y-4">{items.map(renderItem)}</div>
}

export const ValueMoney = ({
  data,
  empty,
  currency,
  decimals,
}: {
  data: number | undefined | null
  empty?: UsualReactNode
  currency?: string
  decimals?: number
}) => {
  return data === undefined || data === null ? empty : formatMoney(data, currency, decimals)
}

export const ValueElement = ({
  data,
  empty = defaultEmpty,
}: {
  data: React.ReactElement<any> | undefined | null
  empty?: UsualReactNode
}) => {
  return data === undefined || data === null ? empty : data
}

export const ValueUnknown = ({
  data,
  empty = defaultEmpty,
  unknown = defaultUnknown,
}: {
  data: unknown | undefined | null
  empty?: UsualReactNode
  unknown?: UsualReactNode
}) => {
  return data === undefined || data === null ? empty : unknown
}

const isEmpty = (data: unknown): boolean => {
  return (
    data === undefined ||
    data === null ||
    (Array.isArray(data) && data.length === 0) ||
    (typeof data === 'string' && !data.trim())
  )
}

const isNegative = (data: unknown): boolean => {
  return typeof data === 'boolean' && !data
}

const isUnknown = (data: unknown): boolean => {
  if (data === null) {
    return false
  }
  if (data instanceof Date) {
    return false
  }
  if (typeof data !== 'object') {
    return false
  }
  if (!Array.isArray(data)) {
    return false
  }
  if (data.length === 0) {
    return false
  }
  if (data.some((item) => item && typeof item !== 'string')) {
    return false
  }
  return true
}

const renderValueByVariant = (variant: ValueVariant, props: Record<string, unknown>): UsualReactNode => {
  switch (variant) {
    case 'string':
      return <ValueString {...(props as React.ComponentProps<typeof ValueString>)} />
    case 'number':
      return <ValueNumber {...(props as React.ComponentProps<typeof ValueNumber>)} />
    case 'boolean':
      return <ValueBoolean {...(props as React.ComponentProps<typeof ValueBoolean>)} />
    case 'date':
      return <ValueDate {...(props as React.ComponentProps<typeof ValueDate>)} />
    case 'badge':
      return <ValueBadge {...(props as React.ComponentProps<typeof ValueBadge>)} />
    case 'money':
      return <ValueMoney {...(props as React.ComponentProps<typeof ValueMoney>)} />
    case 'element':
      return <ValueElement {...(props as React.ComponentProps<typeof ValueElement>)} />
    case 'unknown':
      return <ValueUnknown {...(props as React.ComponentProps<typeof ValueUnknown>)} />
    case 'any':
    default:
      return <ValueAny {...(props as React.ComponentProps<typeof ValueAny>)} />
  }
}

export type ValueBareProps<TVariant extends ValueVariant = 'any'> = {
  variant?: TVariant
} & ValueProps<TVariant>

export const ValueBare = <TVariant extends ValueVariant = 'any'>(props: ValueBareProps<TVariant>) => {
  const { variant, ...rest } = props as ValueBareProps<TVariant> & Record<string, unknown>
  return renderValueByVariant(variant ?? 'any', rest)
}

type ValueViewLayoutProps = {
  label?: string // text above value
  hint?: string // tooltip with text on hover
  description?: string // text under value
  hide?: boolean // do not show if true
  className?: string
}

export type ValueViewProps<TVariant extends ValueVariant = 'any'> = ValueViewLayoutProps & {
  variant?: TVariant
  hideEmpty?: boolean
  hideNegative?: boolean
  hideUnknown?: boolean
} & ValueProps<TVariant>

export const ValueView = <TVariant extends ValueVariant = 'any'>(props: ValueViewProps<TVariant>) => {
  const { variant, label, hint, description, hide, className, hideEmpty, hideNegative, hideUnknown, ...rest } =
    props as ValueViewProps<TVariant> & Record<string, unknown>

  if (hide) {
    return null
  }
  if (hideEmpty && isEmpty(rest.data)) {
    return null
  }
  if (hideNegative && isNegative(rest.data)) {
    return null
  }
  if (hideUnknown && isUnknown(rest.data)) {
    return null
  }

  const valueNode = renderValueByVariant((variant ?? 'any') as ValueVariant, rest)

  const content = (
    <div data-slot="value-view" className={cn('flex min-w-0 flex-col gap-0.5', className)}>
      {label ? <div className="text-xs font-medium text-muted-foreground">{label}</div> : null}
      <div className="text-sm">{valueNode}</div>
      {description ? <div className="text-xs text-muted-foreground">{description}</div> : null}
    </div>
  )

  if (!hint) {
    return content
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>{content}</TooltipTrigger>
      <TooltipContent>{hint}</TooltipContent>
    </Tooltip>
  )
}

export type ValueListItemProps<TData extends Record<string, unknown>> = {
  [TVariant in ValueVariant]: ValueViewLayoutProps & {
    key?: keyof TData
    variant?: TVariant
  } & Omit<ValueProps<TVariant>, 'data'> &
    Pick<Partial<ValueProps<TVariant>>, 'data'>
}[ValueVariant]

export const VALUE_LIST_REST = '...' as const
export type ValueListRest = typeof VALUE_LIST_REST

export type ValueListItemEntry<TData extends Record<string, unknown>> =
  (keyof TData & string) | ValueListRest | ValueListItemProps<TData> | null | undefined | false

export type ValueListProps<TData extends Record<string, unknown>> = {
  data: TData
  hideEmpty?: boolean
  hideNegative?: boolean
  hideUnknown?: boolean
  empty?: UsualReactNode
  unknown?: UsualReactNode
  negative?: UsualReactNode
  positive?: UsualReactNode
  dateVariant?: FormatDateVariant
  // if `only` is true, only items in `items` are rendered. otherwise the
  // remaining keys from `data` are appended at the end. you can also place
  // a single `'...'` entry inside `items` to control where the remaining
  // keys are inserted; in that case `only` is ignored for expansion.
  only?: boolean
  items?: Array<ValueListItemEntry<TData>>
  // when true, render a search input above the list that filters items by
  // their label / key (not by value)
  filterable?: boolean
  filterPlaceholder?: string
  filterEmpty?: UsualReactNode
  className?: string
  listClassName?: string
}

const normalizeItemEntry = <TData extends Record<string, unknown>>(
  entry: ValueListItemEntry<TData>,
): ValueListItemProps<TData> | null => {
  if (!entry) {
    return null
  }
  if (typeof entry === 'string') {
    return { key: entry } as unknown as ValueListItemProps<TData>
  }
  if ((entry as { hide?: boolean }).hide) {
    return null
  }
  return entry as ValueListItemProps<TData>
}

export const ValueList = <TData extends Record<string, unknown>>({
  data,
  hideEmpty,
  hideNegative,
  hideUnknown,
  empty,
  unknown,
  negative,
  positive,
  dateVariant,
  only,
  items,
  filterable,
  filterPlaceholder = 'Filter',
  filterEmpty = 'No matches',
  className,
  listClassName,
}: ValueListProps<TData>) => {
  const [query, setQuery] = React.useState('')

  const defaults: Record<string, unknown> = {
    ...(empty !== undefined && { empty }),
    ...(unknown !== undefined && { unknown }),
    ...(negative !== undefined && { negative }),
    ...(positive !== undefined && { positive }),
    ...(dateVariant !== undefined && { dateVariant, format: dateVariant }),
    ...(hideEmpty !== undefined && { hideEmpty }),
    ...(hideNegative !== undefined && { hideNegative }),
    ...(hideUnknown !== undefined && { hideUnknown }),
  }

  const rawItems = items ?? []
  const restIndices = rawItems.reduce<number[]>((acc, entry, i) => {
    if (entry === VALUE_LIST_REST) {
      acc.push(i)
    }
    return acc
  }, [])
  if (restIndices.length > 1 && !env.mode.is.production) {
    // eslint-disable-next-line no-console
    console.warn(`ValueList: only one "${VALUE_LIST_REST}" entry is allowed in items; using the first`)
  }
  const restIndex = restIndices[0] ?? -1
  const hasRest = restIndex !== -1

  const beforeEntries = hasRest ? rawItems.slice(0, restIndex) : rawItems
  const afterEntries = hasRest ? rawItems.slice(restIndex + 1) : []

  const beforeItems = beforeEntries
    .map((entry) => normalizeItemEntry<TData>(entry))
    .filter((entry): entry is ValueListItemProps<TData> => entry !== null)
  const afterItems = afterEntries
    .map((entry) => normalizeItemEntry<TData>(entry))
    .filter((entry): entry is ValueListItemProps<TData> => entry !== null)
  const explicitKeys = new Set([...beforeItems, ...afterItems].map((item) => item.key as string))

  const shouldExpand = hasRest || !only
  const restItems = shouldExpand
    ? (Object.keys(data) as Array<keyof TData & string>)
        .filter((key) => !explicitKeys.has(key))
        .map((key) => ({ key }) as ValueListItemProps<TData>)
    : []

  const allItems = [...beforeItems, ...restItems, ...afterItems]
  const trimmedQuery = filterable ? query.trim() : ''
  const finalItems = trimmedQuery
    ? allItems
        .map((item) => {
          const key = String(item.key)
          const label = (item.label as string | undefined) ?? toHumanCase(key)
          const score = Math.max(
            fuzzyScore(label, trimmedQuery) ?? -Infinity,
            fuzzyScore(key, trimmedQuery) ?? -Infinity,
          )
          return { item, score }
        })
        .filter((entry) => entry.score !== -Infinity)
        .sort((a, b) => b.score - a.score)
        .map((entry) => entry.item)
    : allItems

  const list =
    finalItems.length === 0 && trimmedQuery ? (
      <div data-slot="value-list-empty" className="text-sm text-muted-foreground">
        {filterEmpty}
      </div>
    ) : (
      <div
        data-slot="value-list"
        className={cn('flex flex-row flex-wrap gap-x-8 gap-y-4', !filterable && className, listClassName)}
      >
        {finalItems.map((item, index) => {
          const { key, label, ...rest } = item as ValueListItemProps<TData> & Record<string, unknown>
          const dataKey = key
          const resolvedLabel = (label as string | undefined) ?? toHumanCase(String(key ?? 'Unknown'))
          const dataResolved = 'data' in item ? item.data : dataKey ? data[dataKey] : undefined
          return (
            <ValueView
              key={(key as string | undefined) ?? index}
              {...(defaults as ValueViewProps)}
              {...(rest as ValueViewProps)}
              data={dataResolved}
              label={resolvedLabel}
            />
          )
        })}
      </div>
    )

  if (!filterable) {
    return list
  }

  return (
    <div data-slot="value-list-wrapper" className={cn('flex flex-col gap-6', className)}>
      <XInput
        icon={<SearchIcon />}
        type="search"
        value={query}
        onChange={(event) => setQuery(event.currentTarget.value)}
        placeholder={filterPlaceholder}
      />

      {list}
    </div>
  )
}
