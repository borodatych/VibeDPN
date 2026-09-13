import { axiomGetSink } from '@/modules/axiom'
import { sharedEnv } from '@/modules/env/shared'
import { sentryGetSink } from '@/modules/sentry/shared'
import type { AnsiColorFormatterOptions, ConsoleFormatter, Sink, TextFormatter } from '@logtape/logtape'
import {
  configureSync,
  getAnsiColorFormatter,
  getConsoleSink,
  getJsonLinesFormatter,
  getLogger,
  type LogRecord,
  type Logger as LogTapeLogger,
} from '@logtape/logtape'
import {
  CREDIT_CARD_NUMBER_PATTERN,
  DEFAULT_REDACT_FIELDS,
  EMAIL_ADDRESS_PATTERN,
  JWT_PATTERN,
  redactByField,
  redactByPattern,
} from '@logtape/redaction'
import { env, getRequestOrUndefined, Point0 } from '@point0/core'
import type { Request0 } from '@point0/core/request0'
import { AppError } from './error.js'

type LogProps = Record<string, unknown>
type LogLevel = 'trace' | 'debug' | 'info' | 'warning' | 'warn' | 'error' | 'fatal'
type LogMethod = 'trace' | 'debug' | 'info' | 'warn' | 'error' | 'fatal'
type LogInput = string | Error | LogProps
type LogCategory = string | readonly string[]

const normalizeLevel = (level: string | undefined): Exclude<LogLevel, 'warn'> | undefined => {
  if (level === 'warn') {
    return 'warning'
  }
  if (
    level === 'trace' ||
    level === 'debug' ||
    level === 'info' ||
    level === 'warning' ||
    level === 'error' ||
    level === 'fatal'
  ) {
    return level
  }
}

const getLogMethodByLevel = (level: LogLevel): LogMethod => (level === 'warning' ? 'warn' : level)

const getCategoryFilter = (filter: string | undefined) => {
  const patterns = filter
    ?.split(',')
    .map((pattern) => pattern.trim())
    .filter(Boolean)

  if (!patterns?.length) {
    return
  }

  const positivePatterns = patterns
    .filter((pattern) => !pattern.startsWith('-'))
    .map((pattern) => globToRegExp(pattern))
  const negativePatternsExceptErrors = patterns
    .filter((pattern) => pattern.startsWith('-') && !pattern.endsWith('!'))
    .map((pattern) => globToRegExp(pattern.slice(1)))
  const negativePatternsWithErrors = patterns
    .filter((pattern) => pattern.startsWith('-') && pattern.endsWith('!'))
    .map((pattern) => globToRegExp(pattern.slice(1, -1)))
  const negativePatterns = [...negativePatternsExceptErrors, ...negativePatternsWithErrors]

  return (record: Pick<LogRecord, 'category' | 'level'>) => {
    const categoryPath = record.category.join(':')
    const included = positivePatterns.length === 0 || positivePatterns.some((pattern) => pattern.test(categoryPath))
    const excluded =
      record.level === 'error' || record.level === 'fatal'
        ? negativePatternsWithErrors.some((pattern) => pattern.test(categoryPath))
        : negativePatterns.some((pattern) => pattern.test(categoryPath))
    return included && !excluded
  }
}

const globToRegExp = (pattern: string) => {
  const escapedPattern = pattern.replace(/[.+?^${}()|[\]\\]/g, String.raw`\$&`).replaceAll('*', '.*')
  return new RegExp(`^${escapedPattern}$`)
}

const normalizeProps = (props: LogProps): LogProps => {
  return Object.fromEntries(
    Object.entries(props).map(([key, value]) => {
      if (value instanceof Error) {
        return [key, AppError.serializePrivate(value)]
      }
      if (value && typeof value === 'object' && 'point' in value && value.point instanceof Point0) {
        return [key, value.point.toString()]
      }
      return [key, value]
    }),
  )
}

// A plain record we spread as structured log fields. Anything else handed to the logger where a value is expected — a
// real `Error`, a host throwable that fails `instanceof Error` (e.g. Bun's `ResolveMessage`), or a primitive — is a
// thrown value to surface, not props.
const isPropsBag = (value: unknown): value is LogProps =>
  typeof value === 'object' &&
  value !== null &&
  (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null)

// Normalize any thrown value to a real `Error`: a genuine `Error` passes through (cause chain + identity preserved),
// everything else (`ResolveMessage`, a string, ...) goes through `AppError.from`, which gives it a message + stack. This is
// what lets `logger.error(message, <unknown>)` surface *any* error, not only `instanceof Error` ones.
const toError = (value: unknown): Error => (value instanceof Error ? value : AppError.from(value))

const write = ({
  logTapeLogger,
  level,
  input,
  category,
  props,
  context,
}: {
  logTapeLogger: LogTapeLogger
  level: LogLevel
  input: LogInput | unknown
  category?: LogCategory
  props?: LogProps | Error | unknown
  context: LogProps
}) => {
  const error1 = input === undefined || typeof input === 'string' || isPropsBag(input) ? undefined : toError(input)
  const error2 = (() => {
    if (props === undefined) {
      return undefined
    }
    // A props bag may still carry an error under `error` — pull it out so it's surfaced, not just flattened away.
    if (isPropsBag(props)) {
      if ('error' in props && props.error !== undefined) {
        const error = toError(props.error)
        delete props.error
        return error
      }
      return undefined
    }
    // The value itself is the error — a real `Error`, a host throwable (`ResolveMessage`), a string, ...
    return toError(props)
  })()
  // Normalize the thrown value to `AppError` (a copy) only to read structured data off it — the full private projection
  // for the log props (name, stack, cause chain, meta; wire publicity never applies to the log path) and the typed
  // `level`. The original error stays in `errorAny` below; that's the instance the sink gets.
  const errorNormalized1 = error1 && AppError.from(error1)
  const errorNormalized2 = error2 && AppError.from(error2)
  const errorProps1 = errorNormalized1?.serializePrivate()
  const errorProps2 = errorNormalized2?.serializePrivate()
  const inputProps = isPropsBag(input) ? input : undefined
  const errorAnyNormalized = errorNormalized1 ?? errorNormalized2
  const errorAny = error1 ?? error2

  const message =
    typeof input === 'string'
      ? input
      : inputProps && 'message' in inputProps && typeof inputProps.message === 'string'
        ? inputProps.message
        : props && typeof props === 'object' && 'message' in props && typeof props.message === 'string'
          ? props.message
          : (error1?.message ?? error2?.message ?? 'Unknown message')

  const normalizedProps = normalizeProps({
    ...getContext(),
    ...context,
    ...inputProps,
    ...errorProps1,
    ...errorProps2,
    ...(isPropsBag(props) ? props : undefined),
  })

  if (message === normalizedProps.message) {
    delete normalizedProps.message
  }

  if (errorAny) {
    // The live instance stays in props for the sentry sink and the pretty formatter. In pretty
    // mode the stack rides the message and the cause is printed by the formatter, so drop both
    // from the flattened props; in json mode they stay — structured fields are the point.
    normalizedProps.error = errorAny
    if (logMode === 'pretty') {
      delete normalizedProps.stack
      delete normalizedProps.cause
    }
  }
  // LogTape parses its first argument as a message template, so untrusted text (a message or a stack — e.g. a zod
  // error whose message is the issues JSON) must have its braces doubled, or every `{...}` renders as `undefined`.
  const escapeLogTapeTemplate = (value: string) => value.replaceAll('{', '{{').replaceAll('}', '}}')
  const messageWithStack = escapeLogTapeTemplate(
    errorAny && env.side.is.server && logMode === 'pretty' ? `${message}\n${errorAny.stack}` : message,
  )

  const isNormalizedPropsEmpty = Object.keys(normalizedProps).length === 0
  const logArgs = isNormalizedPropsEmpty ? [messageWithStack] : [messageWithStack, normalizedProps]

  if (category) {
    logTapeLogger = getChildLogger(logTapeLogger, category)
  }

  // The error's own opinion wins over the call site: an explicit `level` (error0 levelPlugin) first, else an `expected`
  // error is a `warn` — it's routine, not a fault — so expected 404s never sit in the error stream.
  const resolvedLevel = normalizeLevel(errorAnyNormalized?.level) ?? (errorAnyNormalized?.expected ? 'warning' : level)
  const method = getLogMethodByLevel(resolvedLevel)
  logTapeLogger[method](...(logArgs as [any]))
}

const getChildLogger = (logTapeLogger: LogTapeLogger, category: LogCategory) => {
  if (typeof category === 'string') {
    return logTapeLogger.getChild(category)
  }

  if (category.length === 0) {
    return logTapeLogger
  }

  return logTapeLogger.getChild(category as readonly [string, ...string[]])
}

const clientContextMemory = {}
const serverContextMemory = {}
declare module '@point0/core/request0' {
  interface RequestState {
    loggerContext?: Record<string, unknown>
  }
  interface RequestCache {
    loggerContext?: Record<string, unknown>
  }
}

const rememberContext = ({
  logTapeLogger,
  type,
  extraContext,
  currentContext,
}: {
  logTapeLogger: LogTapeLogger
  type: 'state' | 'cache' | 'global' | 'current' | { state: Request0 } | { cache: Request0 }
  extraContext: LogProps
  currentContext: LogProps
}) => {
  if (type === 'current') {
    return Object.assign(currentContext, extraContext)
  }
  if (env.side.is.client) {
    if (type === 'global') {
      return Object.assign(clientContextMemory, extraContext)
    }
    logTapeLogger.error(new Error('Remembering request context is not supported on client'))
    return {}
  }
  if (type === 'global') {
    return Object.assign(serverContextMemory, extraContext)
  }
  const contextType =
    typeof type === 'string' ? type : 'state' in type ? 'state' : 'cache' in type ? 'cache' : undefined
  const request =
    typeof type === 'string'
      ? getRequestOrUndefined()
      : 'state' in type
        ? type.state
        : 'cache' in type
          ? type.cache
          : undefined
  if (request) {
    if (contextType === 'state') {
      if (!request.state.loggerContext) {
        request.state.loggerContext = {}
      }
      return Object.assign(request.state.loggerContext, extraContext)
    }
    if (contextType === 'cache') {
      if (!request.cache.loggerContext) {
        request.cache.loggerContext = {}
      }
      return Object.assign(request.cache.loggerContext, extraContext)
    }
    logTapeLogger.error(new Error('Request context type not defined while remembering request context'))
    return {}
  }
  logTapeLogger.error(new Error('Request not found while remembering request context'))
  return {}
}

const getContext = () => {
  if (env.side.is.client) {
    return clientContextMemory
  }
  const request = getRequestOrUndefined()
  const serverContext = {}
  Object.assign(serverContext, serverContextMemory)
  if (request) {
    if (request.state.loggerContext) {
      Object.assign(serverContext, request.state.loggerContext)
    }
    if (env.mode.is.production) {
      Object.assign(serverContext, {
        request: {
          id: request.id,
          ip: request.from.ip,
          userAgent: request.from.userAgent,
          pathname: request.location.pathname,
          method: request.method,
          variant: request.variant.type,
          ...('point' in request.variant ? { point: request.variant.point?.id } : {}),
        },
      })
    } else {
      Object.assign(serverContext, {
        request: {
          pathname: request.location.pathname,
          method: request.method,
          ...('point' in request.variant ? { point: request.variant.point?.id } : {}),
        },
      })
    }
    // The authenticated user, read straight from the request cache (`getMe` sets it) so every line of a request carries
    // who made it — no `remember` call to keep in sync. `undefined` (not read yet) / `null` (anonymous) are omitted.
    const me = request.cache.me
    if (me) {
      Object.assign(serverContext, {
        me: {
          id: me.user.id,
          admin: me.admin,
          ...(me.session.impersonatedBy ? { impersonated: me.session.impersonatedBy } : {}),
        },
      })
    }
  }
  return serverContext
}

const createLogger = (logTapeLogger: LogTapeLogger, context: LogProps = {}): Logger => ({
  context,
  child: (category, extraContext) => {
    const childLogger = getChildLogger(logTapeLogger, category)
    return createLogger(childLogger, { ...context, ...extraContext })
  },
  with: (extraContext) => createLogger(logTapeLogger, { ...context, ...extraContext }),
  add: (extraContext) => Object.assign(context, extraContext),
  remember: (type, extraContext) => rememberContext({ logTapeLogger, type, extraContext, currentContext: context }),
  log: ({ level, category, input, props }) => write({ logTapeLogger, level, category, input, props, context }),
  trace: (input, props) => write({ logTapeLogger, level: 'trace', input, props, context }),
  debug: (input, props) => write({ logTapeLogger, level: 'debug', input, props, context }),
  info: (input, props) => write({ logTapeLogger, level: 'info', input, props, context }),
  warn: (input, props) => write({ logTapeLogger, level: 'warning', input, props, context }),
  error: (input, props) => write({ logTapeLogger, level: 'error', input, props, context }),
  fatal: (input, props) => write({ logTapeLogger, level: 'fatal', input, props, context }),
})

const getPrettyFormatter = (options?: AnsiColorFormatterOptions) => {
  const ansiColorFormatter = getAnsiColorFormatter({
    timestamp: 'time',
    level: 'abbr',
    levelStyle: 'bold',
    categoryStyle: 'dim',
    category: ':',
    ...options,
  })

  return (record: LogRecord): [string, ...unknown[]] => {
    const properties = record.properties
    const { error, ...restProperties } = properties as typeof properties & { error?: Error }
    const recordWithoutError = { ...record, properties: restProperties }
    const isRestPropertiesEmpty = Object.keys(restProperties).length === 0
    const causeArgs = error?.cause ? [error.cause] : []

    if (env.side.is.server) {
      const messages: [string, ...unknown[]] = [
        ansiColorFormatter(recordWithoutError),
        ...causeArgs,
        ...(isRestPropertiesEmpty ? [] : [restProperties]),
      ]
      return messages.length === 1 ? (messages[0] as never) : messages
    }

    const messages: string | [string, ...unknown[]] = [
      ansiColorFormatter(recordWithoutError),
      ...causeArgs,
      ...(isRestPropertiesEmpty ? [] : [restProperties]),
      ...(error ? [error] : []),
    ]
    return messages.length === 1 ? (messages[0] as never) : messages
  }
}

const getUglyFormatter = () => {
  return (record: LogRecord) => {
    const properties = record.properties
    const { error, ...restProperties } = properties
    const isRestPropertiesEmpty = Object.keys(restProperties).length === 0
    return [
      record.category.join(':'),
      ...record.message,
      ...(isRestPropertiesEmpty ? [] : [restProperties]),
      ...(error && env.side.is.client ? [error] : []),
    ]
  }
}

// This module configures the logger while it evaluates, and it evaluates during `point0 build` too — where there is no
// env at all (the image copies no `.env`, and a platform hands a build no service variables). So the host is read the
// one way that survives that: absent means "not prod". A host that IS set still has to be one of the declared values.
const isProdHost = sharedEnv.getOrUndefined('HOST_ENV') === 'prod'

const wrapSinkWithSensetiveRedaction = (sink: Sink) => {
  if (!isProdHost) {
    return sink
  }
  return redactByField(sink, ['secret', /api[-_]?key/i, ...DEFAULT_REDACT_FIELDS])
}

const wrapFormatterWithSensetiveRedaction = (formatter: TextFormatter | ConsoleFormatter) => {
  if (!isProdHost) {
    return formatter
  }

  return redactByPattern(formatter as ConsoleFormatter, [
    EMAIL_ADDRESS_PATTERN,
    CREDIT_CARD_NUMBER_PATTERN,
    JWT_PATTERN,
  ])
}

const categoryFilter = getCategoryFilter(sharedEnv.LOG_FILTER)

// unset falls back to json in production, pretty otherwise — that default lives in `sharedEnvShape.LOG_MODE`
const logMode = sharedEnv.LOG_MODE

// One sinks map, built per side: `console` + `sentry` everywhere, `axiom` only on the server (it stores every record).
// On the client build the Point0 compiler stubs the server-only `axiomGetSink` import and prunes this branch, so
// `@axiomhq/js` never reaches the browser. The root logger's sink list is derived from the actual keys
// (`Object.keys(sinks)`), so adding or removing a sink here needs no second edit.
const sinks: Record<string, Sink> = {
  console: wrapSinkWithSensetiveRedaction(
    getConsoleSink({
      formatter: wrapFormatterWithSensetiveRedaction(
        logMode === 'json'
          ? env.side.is.client
            ? getUglyFormatter()
            : getJsonLinesFormatter({ categorySeparator: ':', properties: 'flatten' })
          : getPrettyFormatter(),
      ),
      // Server only: a non-blocking console sink is async-disposable, and `configureSync` (below) rejects those — in the
      // browser it throws "Async disposables cannot be used with configureSync()".
      nonBlocking: env.mode.is.production && env.side.is.server,
    }),
  ),
  sentry: sentryGetSink(),
  // Server-only log store. Same redaction wrapper as the console sink, so secrets never land in Axiom.
  ...(env.side.is.server ? { axiom: wrapSinkWithSensetiveRedaction(axiomGetSink()) } : {}),
}

configureSync({
  reset: true,
  filters: {
    ...(categoryFilter ? { categoryFilter } : {}),
  },
  sinks,
  loggers: [
    {
      category: [],
      lowestLevel: normalizeLevel(sharedEnv.LOG_LEVEL) ?? (env.mode.is.production ? 'info' : 'debug'),
      sinks: Object.keys(sinks),
      filters: [...(categoryFilter ? ['categoryFilter'] : [])],
    },
    {
      category: ['logtape', 'meta'],
      lowestLevel: 'warning',
      sinks: ['console'],
    },
  ],
})

export type Logger = {
  context: LogProps
  child: (category: LogCategory, context?: LogProps) => Logger
  with: (context: LogProps) => Logger
  /** same as remember('current', context) */
  add: (context: LogProps) => LogProps
  /**
   * - remember('request', context) adding context to request state
   * - remember('global', context) adding context to global context
   * - remember('current', context) is same as add(context), just extends current logger context
   */
  remember: (
    type: 'state' | 'cache' | 'global' | 'current' | { state: Request0 } | { cache: Request0 },
    context: LogProps,
  ) => LogProps
  log: (options: { level: LogLevel; category?: string | string[]; input: LogInput; props?: LogProps }) => void
  trace: (input: LogInput, props?: LogProps) => void
  debug: (input: LogInput, props?: LogProps) => void
  info: (input: LogInput, props?: LogProps) => void
  warn: (input: LogInput, props?: LogProps) => void
  error: (input: LogInput | unknown, props?: LogProps | Error | unknown) => void
  fatal: (input: LogInput, props?: LogProps) => void
}

/**
 * Project logger. Powered by LogTape. Always start with `logger.child('category')` — only `child`, `log`, and
 * `remember` are exposed on the root so module logs don't get filed under the empty category.
 *
 * Configured by env: `LOG_LEVEL`, `LOG_MODE` (`pretty` | `json`), and `LOG_FILTER` (comma-separated glob list, prefix
 * `-` to exclude, suffix `!` to also exclude errors).
 *
 * Error values are serialized via `AppError.serializePrivate` — the full operator view (name, stack, cause chain),
 * whether passed as `input` or under `props.error`. Wire publicity gating never applies to logs.
 *
 * @example
 *   const l = logger.child('auth')
 *   l.info('Signed in', { userId })
 *   l.error('Failed to verify', error)
 *   l.remember('state', { userId }) // attach to this request
 *
 * @tags rule, logger, logtape
 * @related AppError
 */
export const logger = createLogger(getLogger([])) as Pick<Logger, 'child' | 'log' | 'remember'>
