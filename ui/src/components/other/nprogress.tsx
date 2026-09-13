import { useOnNavigate } from '@point0/core/navigation'
import nprogress from 'nprogress'

export const NProgress = () => {
  useOnNavigate(() => {
    const timeout = setTimeout(() => {
      nprogress.start()
    }, 30)
    return () => {
      clearTimeout(timeout)
      nprogress.done()
    }
  })
  return null
}
