import { Spinner } from '@/components/ui/spinner'
import { ErrorComponent, ErrorPageComponent } from '@/components/other/error'
import { AppError } from '@/lib/error'
import { logger } from '@/lib/logger'
import { axiomMetricsMiddleware } from '@/modules/axiom'
import { cacheControl } from '@point0/cache-control'
import { compress } from '@point0/compress'
import { authServer } from '@/modules/auth/server'
import { withSocketClientIp } from '@/modules/auth/client-ip'
import { CORE_API_PREFIX, coreApiProxy } from '@/modules/core/proxy'
import { CookieStore } from '@point0/core/cookie-store'
import { Point0 } from '@point0/core'
import { zodSchemaHelper } from '@point0/core/schema/zod'
import superjson from 'superjson'
import { sharedEnv } from '@/modules/env/shared'
import { useT } from '@/modules/i18n/use-t'
import { useHead } from '@unhead/react'

// The loading title is set here, not in head(): head() runs outside React and cannot read the language of the panel
const PageLoading = () => {
  useHead({ title: useT()('app.loading') })
  return <Spinner size="3xl" className="m-auto" />
}

/**
 * Project-wide Point0 root. Wires shared transformer, schema helper, error class, query defaults, error/loading
 * components, and the auth + openapi middlewares.
 *
 * Build every point off this root, or off a module-level `*Base` derived from it — never a bare `Point0.lets`. The base
 * carries `basePath` and gating plugins, so pages/queries/mutations inherit them.
 *
 * @tags rule, point0, root
 */
export const root = Point0.lets
  .root()
  .serverUrl(sharedEnv.SERVER_URL)
  .clientUrl(sharedEnv.CLIENT_URL)
  .transformer(superjson)
  .schemaHelper(zodSchemaHelper())
  .errorClass(AppError)
  .prefetchPageOnNavigate('pageDehydratedStateAndClientQuery')
  .prefetchPageOnLinkHover('pageDehydratedStateAndClientQuery')
  .queryOptions({
    retry: false,
    retryOnMount: false,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    refetchInterval: false,
    refetchIntervalInBackground: false,
    staleTime: 1 * 60 * 1000, // 1 minute
  })
  .on('error', ({ side, name, error, meta }) => {
    logger.log({
      level: 'error',
      category: 'point0',
      input: error,
      props: {
        side,
        name,
        ...meta,
      },
    })
  })
  .head('global', ({ error }) => {
    return {
      ...(error ? { title: error.message } : {}),
      titleTemplate: '%s | VibeDPN',
      // <html lang> is the language of the panel: generalLayout sets it from the language query
    }
  })
  .loading(() => {
    return <PageLoading />
  })
  .error(({ error }) => {
    return <ErrorPageComponent error={error} />
  })
  .componentError(({ error }) => {
    return <ErrorComponent error={error} />
  })
  .middleware(axiomMetricsMiddleware)
  .middleware(compress())
  .middleware(cacheControl())
  .use(CookieStore.plugin())
  .middleware('/api/auth/*', async ({ request }) => await authServer.handler(withSocketClientIp(request)))
  .middleware(`${CORE_API_PREFIX}/*`, coreApiProxy)
  .root()
