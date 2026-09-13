import { useChanged } from '@/components/hooks/use-changed'
import type { Dispatch, ReactNode, SetStateAction } from 'react'
import { useState } from 'react'
import { useDebounce } from 'use-debounce'

export type DebouncedRenderProps<TValue> = {
  value: TValue
  setValue: Dispatch<SetStateAction<TValue>>
  debouncedValue: TValue
}

export type DebouncedProps<TValue> = {
  value: TValue
  onChange: (value: TValue) => void
  delay?: number
  children: (props: DebouncedRenderProps<TValue>) => Exclude<ReactNode, Promise<any>>
}

export const Debounced = <TValue,>({ value, onChange, delay = 400, children }: DebouncedProps<TValue>) => {
  const [committedValue, setCommittedValue] = useState(value)
  const [localValue, setLocalValue] = useState(value)
  const [debouncedValue] = useDebounce(localValue, delay)

  if (!Object.is(value, committedValue)) {
    setCommittedValue(value)
    setLocalValue(value)
  }

  useChanged(() => {
    if (!Object.is(debouncedValue, value)) {
      onChange(debouncedValue)
    }
  }, [debouncedValue, onChange, value])

  return children({
    value: localValue,
    setValue: setLocalValue,
    debouncedValue,
  })
}
