import { useEffect, useState } from 'react'

export type Breakpoint = 'sm' | 'md' | 'lg' | 'xl' | '2xl'
export type BreakpointQuery = Breakpoint | `max-${Breakpoint}`
const breakpointQueryProperties = {
  sm: '--breakpoint-sm-match',
  md: '--breakpoint-md-match',
  lg: '--breakpoint-lg-match',
  xl: '--breakpoint-xl-match',
  '2xl': '--breakpoint-2xl-match',
  'max-sm': '--breakpoint-max-sm-match',
  'max-md': '--breakpoint-max-md-match',
  'max-lg': '--breakpoint-max-lg-match',
  'max-xl': '--breakpoint-max-xl-match',
  'max-2xl': '--breakpoint-max-2xl-match',
} satisfies Record<BreakpointQuery, string>

const breakpointProbeClassName = [
  '[--breakpoint-sm-match:0] sm:[--breakpoint-sm-match:1]',
  '[--breakpoint-md-match:0] md:[--breakpoint-md-match:1]',
  '[--breakpoint-lg-match:0] lg:[--breakpoint-lg-match:1]',
  '[--breakpoint-xl-match:0] xl:[--breakpoint-xl-match:1]',
  '[--breakpoint-2xl-match:0] 2xl:[--breakpoint-2xl-match:1]',
  '[--breakpoint-max-sm-match:0] max-sm:[--breakpoint-max-sm-match:1]',
  '[--breakpoint-max-md-match:0] max-md:[--breakpoint-max-md-match:1]',
  '[--breakpoint-max-lg-match:0] max-lg:[--breakpoint-max-lg-match:1]',
  '[--breakpoint-max-xl-match:0] max-xl:[--breakpoint-max-xl-match:1]',
  '[--breakpoint-max-2xl-match:0] max-2xl:[--breakpoint-max-2xl-match:1]',
].join(' ')

let breakpointProbe: HTMLDivElement | undefined

function getBreakpointProbe() {
  if (breakpointProbe?.isConnected) {
    return breakpointProbe
  }

  breakpointProbe = document.createElement('div')
  breakpointProbe.ariaHidden = 'true'
  breakpointProbe.className = breakpointProbeClassName
  Object.assign(breakpointProbe.style, {
    contain: 'strict',
    height: '0',
    pointerEvents: 'none',
    position: 'fixed',
    width: '0',
  })

  document.body.append(breakpointProbe)

  return breakpointProbe
}

export function useBreakpoint(name: BreakpointQuery) {
  const [matches, setMatches] = useState(false)

  useEffect(() => {
    const probe = getBreakpointProbe()
    const property = breakpointQueryProperties[name]

    const update = () => {
      setMatches(getComputedStyle(probe).getPropertyValue(property).trim() === '1')
    }

    update()
    window.addEventListener('resize', update)

    return () => {
      window.removeEventListener('resize', update)
    }
  }, [name])

  return matches
}
