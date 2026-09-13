import type { DependencyList, EffectCallback } from 'react'
import { useEffect, useRef } from 'react'
import { stringify as stringifySafe } from 'safe-stable-stringify'

type ChangedDeps<TDeps extends DependencyList> = {
  [TKey in keyof TDeps]: boolean
}
type ChangedEffectCallback<TDeps extends DependencyList> = (
  prevDeps: TDeps,
  isChangedDeps: ChangedDeps<TDeps>,
) => ReturnType<EffectCallback>
type ChangedEffectOptions = {
  initial?: boolean
  stringify?: boolean
}

export const useChanged = <TDeps extends DependencyList>(
  effect: ChangedEffectCallback<TDeps>,
  deps: TDeps,
  options: ChangedEffectOptions = {},
): void => {
  const { initial: triggerOnFirst = false, stringify: stringifyOnCompare = true } = options
  const isFirstRef = useRef(true)
  const prevDepsRef = useRef<TDeps>(deps)

  useEffect(() => {
    const prevDeps = prevDepsRef.current
    const isFirst = isFirstRef.current
    prevDepsRef.current = deps

    if (isFirst) {
      isFirstRef.current = false

      if (!triggerOnFirst) {
        return
      }
    }

    const isChangedDeps = deps.map((dep, index) => {
      if (isFirst) {
        return false
      }

      const prevDep = prevDeps[index]
      return stringifyOnCompare ? stringifySafe(prevDep) !== stringifySafe(dep) : !Object.is(prevDep, dep)
    }) as ChangedDeps<TDeps>

    const isSomeChanged = isChangedDeps.some(Boolean)
    const shouldTriggerEvenIfNotChanged = triggerOnFirst && isFirst

    if (!isSomeChanged && !shouldTriggerEvenIfNotChanged) {
      return
    }

    return effect(prevDeps, isChangedDeps)
  }, deps)
}
