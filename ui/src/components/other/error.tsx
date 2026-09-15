// import { redirectPlugin } from '@1gr14/error0/plugins/point0-redirect'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Section } from '@/components/ui/section'
import { routes } from '@/generated/point0/routes'
import { AppError } from '@/lib/error'
import { Link } from '@/lib/navigation'
import type { T } from '@/modules/i18n/base'
import { useT } from '@/modules/i18n/use-t'
import { cn } from '@/utils'
import { ClientOnly, env } from '@point0/core'
import React, { useMemo } from 'react'

export const useError = (error: unknown, t: T, overrides?: ErrorComponetProps): ErrorComponetProps => {
  const error0 = useMemo(() => (!error ? undefined : AppError.from(error)), [error])

  if (!error0) {
    return {
      title: t('error.unknown.title'),
      description: t('error.unknown.description'),
      ...overrides,
    }
  }
  if (error0.code === 'UNAUTHORIZED') {
    return {
      title: error0.message,
      description: (
        <>
          {t('error.signIn.before')}{' '}
          <Link route="signIn" className="text-blue-500 hover:text-blue-600">
            {t('error.signIn.link')}
          </Link>{' '}
          {t('error.signIn.after')}
        </>
      ),
      stack: error0.stack,
      destructive: true,
      ...overrides,
    }
  }
  if (error0.code === 'FORBIDDEN') {
    return {
      title: error0.message,
      stack: error0.stack,
      destructive: true,
      ...overrides,
    }
  }
  if (error0.status === 404) {
    return {
      title: t('error.notFound'),
      description: error0.message,
      stack: error0.stack,
      destructive: true,
      ...overrides,
    }
  }
  return {
    title: t('error.unknown.title'),
    description: error0.message,
    stack: error0.stack,
    destructive: true,
    ...overrides,
  }
}

export type ErrorComponetProps = {
  title?: React.ReactNode
  description?: React.ReactNode
  content?: React.ReactNode
  stack?: string | undefined
  destructive?: boolean
}

/**
 * The error alert with an explicit translator: the root error boundary renders it outside the app providers, where the
 * language query is not available, and passes the English base.
 */
export const ErrorView = ({
  error,
  className,
  t,
  ...overrides
}: ErrorComponetProps & { error?: unknown; className?: string; t: T }) => {
  const { title, description, stack, destructive, content } = useError(error, t, overrides)
  return (
    <Alert className={cn('', className, destructive ? 'border-destructive' : 'border-border')}>
      <AlertTitle className={cn('text-xl', destructive ? 'text-destructive' : undefined)}>{title}</AlertTitle>
      <AlertDescription className={cn('text-lg', destructive ? 'text-destructive/80' : undefined)}>
        {description}
      </AlertDescription>
      {!!content && <div className="mt-4">{content}</div>}
      {!!stack && !env.mode.is.production && (
        <ClientOnly>
          <pre className="mt-4 overflow-x-auto font-mono text-xs leading-relaxed">
            <code>{stack}</code>
          </pre>
        </ClientOnly>
      )}
    </Alert>
  )
}

export const ErrorComponent = (props: ErrorComponetProps & { error?: unknown; className?: string }) => {
  const t = useT()
  return <ErrorView {...props} t={t} />
}

export const ErrorPageComponent = ({
  error,
  size = 'lg',
  className,
  ...overrides
}: ErrorComponetProps & { error?: unknown; size?: 'lg' | 'sm'; className?: string }) => {
  const t = useT()
  const { title, description, stack, destructive, content } = useError(error, t, overrides)
  return (
    <div
      className={cn(
        '[&:not(:where([data-layout-content]_*))]:flex [&:not(:where([data-layout-content]_*))]:min-h-full [&:not(:where([data-layout-content]_*))]:w-full [&:not(:where([data-layout-content]_*))]:flex-col [&:not(:where([data-layout-content]_*))]:items-center [&:not(:where([data-layout-content]_*))]:justify-center [&:not(:where([data-layout-content]_*))]:p-4',
        className,
      )}
    >
      <Section
        h={1}
        size={size === 'sm' ? 'lg' : '2xl'}
        title={title}
        description={description}
        className={'[&:not(:where([data-layout-content]_*))]:w-full [&:not(:where([data-layout-content]_*))]:max-w-2xl'}
        titleClassName={destructive ? 'text-destructive' : undefined}
        descriptionClassName={destructive ? 'text-destructive' : undefined}
      >
        {content}
        {!!stack && !env.mode.is.production && (
          <ClientOnly>
            <pre className="overflow-x-auto font-mono text-xs leading-relaxed not-first:mt-4">
              <code>{stack}</code>
            </pre>
          </ClientOnly>
        )}
        <div className="not-first:mt-6 [&:where([data-layout-content]_*)]:hidden">
          <Button to={routes.home()} size="xl" variant="outline">
            {t('error.goHome')}
          </Button>
        </div>
      </Section>
    </div>
  )
}
