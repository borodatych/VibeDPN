import { createMock } from '@point0/core/virtual'
import { type expectTypeOf as expectTypeOfOriginal } from 'bun:test'

export const expectTypeOf = createMock() as typeof expectTypeOfOriginal

export type Prettify<T extends object> = {
  [K in keyof T]: T[K]
} & {}

/**
 * `Omit` that distributes over unions, so a discriminated union (e.g. a component's props that embed
 * `InferNavigation.LinkProps`) keeps its branches instead of collapsing to common keys. Use this when re-typing or
 * forwarding props of a component whose props are a discriminated union.
 */
export type DistributiveOmit<T, K extends PropertyKey> = T extends unknown ? Omit<T, K> : never
