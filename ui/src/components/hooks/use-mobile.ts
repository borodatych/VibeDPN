import { useBreakpoint } from '@/components/hooks/use-breakpoint'

export function useIsMobile() {
  return useBreakpoint('max-md')
}
