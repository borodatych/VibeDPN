import { useEffect, useRef, useState } from 'react'

type UseDefinedOptions = {
  enabled?: boolean
}
export function useDefined<T>(value: T, fallback?: undefined, options?: UseDefinedOptions): T
export function useDefined<T>(value: T, fallback: NonNullable<T>, options?: UseDefinedOptions): NonNullable<T>
export function useDefined<T>(value: T, fallback?: NonNullable<T>, options?: UseDefinedOptions) {
  const [current, setCurrent] = useState(value)
  const fallbackRef = useRef(fallback)
  useEffect(() => {
    if (!value || options?.enabled === false) {
      return
    }
    setCurrent(value)
  }, [value, options?.enabled])
  if (options?.enabled === false) {
    return value
  }
  return (value || current || fallbackRef.current) as never
}
