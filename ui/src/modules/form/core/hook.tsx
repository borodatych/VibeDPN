/* eslint-disable react-hooks/refs */
import { AppError } from '@/lib/error'
import { logger } from '@/lib/logger'
import { isPromiseLike } from '@/utils'
import { zodResolver } from '@hookform/resolvers/zod'
import { useCallback, useEffect, useMemo, useRef } from 'react'
import {
  useForm,
  type Control,
  type DefaultValues,
  type FieldErrors,
  type FieldPath,
  type FieldValues,
  type FormState,
  type UseFormWatch as RhfUseFormWatch,
  type UseFormClearErrors,
  type UseFormGetFieldState,
  type UseFormGetValues,
  type UseFormProps,
  type UseFormRegister,
  type UseFormReset,
  type UseFormResetField,
  type UseFormReturn,
  type UseFormSetError,
  type UseFormSetFocus,
  type UseFormSetValue,
  type UseFormSubscribe,
  type UseFormTrigger,
  type UseFormUnregister,
} from 'react-hook-form'
import { toast } from 'sonner'
import type { z } from 'zod'
import { useFFormAlert } from './alert'
import { useFFormSubscribe, type UseFFormSubscribe } from './subscribe'
import { useFValues, type UseFValues, type ValuesValidSnapshot } from './values'

const l = logger.child('form')

const SUBMIT_ON_CHANGE_DEFAULT_DEBOUNCE_MS = 400

export type FormButtonType = 'submit' | 'send' | 'reset' | 'clear'

export type FormSettings = {
  buttonDisabledOnFormInvalid: boolean
  buttonDisabledOnFormPristine: boolean
  fieldDisabledOnFormSubmitting: boolean
}

export type FFormFieldBundle<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = {
  form: UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput>
  name: TName
}

export type FFormButtonBundle<
  TType extends FormButtonType = FormButtonType,
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = {
  form: UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput>
  type: TType
}

export type FFormAlertKind = 'success' | 'validationError' | 'submitError'

export type FFormAlert = {
  kind: FFormAlertKind
  message: string
}

export type UseFFormAlertBoundProps = {
  /** Restrict the result to one or more alert kinds. */
  kind?: FFormAlertKind | FFormAlertKind[]
}

export type UseFFormAlertBound = (props?: UseFFormAlertBoundProps) => FFormAlert | null

export type FFormOnSubmit<
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = (
  inputParsed: TTransformedValues,
  inputOriginal: TFieldValues,
  event?: React.BaseSyntheticEvent,
) => Promise<TSubmitOutput> | TSubmitOutput

export type FFormOnSuccess<
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = (
  submitOutput: TSubmitOutput,
  inputParsed: TTransformedValues,
  inputOriginal: TFieldValues,
) => Promise<TSubmitOutput | void> | TSubmitOutput | void

export type FFormOnSettled<
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = (
  props:
    | { status: 'success'; submitOutput: TSubmitOutput; inputParsed: TTransformedValues; inputOriginal: TFieldValues }
    | { status: 'error'; error: unknown },
) => void

export type UseFFormProps<
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = UseFormProps<TFieldValues, any, TTransformedValues> & {
  id?: string
  schema?: z.ZodType<TTransformedValues, TFieldValues>
  onSubmit?: FFormOnSubmit<TFieldValues, TTransformedValues, TSubmitOutput>
  onSuccess?: FFormOnSuccess<TFieldValues, TTransformedValues, TSubmitOutput>
  onSettled?: FFormOnSettled<TFieldValues, TTransformedValues, TSubmitOutput>
  submitOnMount?: boolean | unknown[]
  /**
   * Auto-submit on value changes.
   *
   * - `true` → debounce 400ms
   * - `<number>` → debounce that many ms
   * - `false` / `undefined` → disabled
   */
  submitOnChange?: boolean | number
  toastOnSuccess?: string | boolean | ((submitOutput: TSubmitOutput) => string)
  toastOnValidationError?: boolean | string | ((errors: FieldErrors<TFieldValues>) => string)
  toastOnSubmitError?: boolean | string | ((error: unknown) => string)
  alertOnSuccess?: string | boolean | ((submitOutput: TSubmitOutput) => string)
  alertOnValidationError?: boolean | string | ((errors: FieldErrors<TFieldValues>) => string)
  alertOnSubmitError?: boolean | string | ((error: unknown) => string)
  alertOnSuccessDuration?: number
  alertOnValidationErrorDuration?: number
  alertOnSubmitErrorDuration?: number
  onSubmitError?: (error: unknown) => void
  onValidationError?: (errors: FieldErrors<TFieldValues>) => void
  buttonDisabledOnFormInvalid?: boolean
  buttonDisabledOnFormPristine?: boolean
  fieldDisabledOnFormSubmitting?: boolean
  clearFormOnSuccess?: boolean | null
  use?: (form: UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput>) => void
}

/**
 * A widened `UseFFormReturn` for components that accept any form (e.g. `<XPagination form={...} />`, `<FButton
 * form={...} />`).
 *
 * Why this exists instead of `UseFFormReturn<any, any, any>`:
 *
 * `UseFFormReturn<T>` has fields whose types embed `T` in _contravariant_ positions (callback parameters):
 *
 * 1. `control._options.validate: ValidateForm<T>` — its callback param is `name?: FieldPath<T> | FieldPath<T>[]`.
 * 2. `useSubscribe` / `useValues` — both accept payloads that include `form?: UseFFormReturn<T, any, any>` as an option.
 *
 * RHF's `FieldPath<any>` resolves to `string` (not `any`) due to distributive mapped types, and (2) self-references
 * `UseFFormReturn<T>` recursively, so `UseFFormReturn<MyForm>` is NOT structurally assignable to `UseFFormReturn<any,
 * any, any>`.
 *
 * We widen the offending fields so the structural compare short-circuits and any concrete `UseFFormReturn<T>` flows in.
 * Consumers using this type opt out of the typed payloads for `useSubscribe` / `useValues` (acceptable trade-off for
 * "form-agnostic" components like pagination/button).
 */
export type AnyUseFFormReturn<
  TFieldValues extends FieldValues = any,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = any,
> = Omit<
  UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput>,
  'control' | 'useSubscribe' | 'useValues' | 'field' | 'button' | 'register'
> & {
  control: Omit<Control<TFieldValues, any, TTransformedValues>, '_options'> & { _options: any }
  useSubscribe: (payload: any) => void
  useValues: (...args: any[]) => any
  field: (...ags: any[]) => any
  button: (...ags: any[]) => any
  register: (...args: any[]) => any
}
export const fromAnyForm = <
  TFieldValues extends FieldValues = any,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = any,
>(
  form: AnyUseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput>,
): UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput> => form

export type UseFFormReturn<
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = {
  // Optional form id; when set, also used as a prefix for generated field ids.
  id: string | undefined

  // RHF passthroughs (stable identity; read latest via getters)
  control: Control<TFieldValues, any, TTransformedValues>
  register: UseFormRegister<TFieldValues>
  getValues: UseFormGetValues<TFieldValues>
  setValue: UseFormSetValue<TFieldValues>
  setError: UseFormSetError<TFieldValues>
  clearErrors: UseFormClearErrors<TFieldValues>
  trigger: UseFormTrigger<TFieldValues>
  getFieldState: UseFormGetFieldState<TFieldValues>
  resetField: UseFormResetField<TFieldValues>
  unregister: UseFormUnregister<TFieldValues>
  setFocus: UseFormSetFocus<TFieldValues>
  subscribe: UseFormSubscribe<TFieldValues>
  watch: RhfUseFormWatch<TFieldValues>
  reset: UseFormReset<TFieldValues>
  formState: FormState<TFieldValues>

  // App-level actions
  handleSubmit: (event?: React.BaseSyntheticEvent) => Promise<void>
  submit: () => void
  send: (values: TFieldValues) => Promise<TSubmitOutput>
  clear: (defaultValues?: DefaultValues<TFieldValues>) => void

  // App-level alert state (sourced by the submit/validation pipeline; also user-settable).
  // Reads are non-reactive on their own — use `useAlert` (or `<FAlert />`) to subscribe.
  alert: FFormAlert | null
  setAlert: (alert: FFormAlert | null) => void

  // App-level subscriptions (bound: form is pre-injected)
  useValues: UseFValues<TFieldValues, TTransformedValues>
  useSubscribe: UseFFormSubscribe<TFieldValues>
  useAlert: UseFFormAlertBound

  // Typed register helpers (nested-form safe)
  field: <TName extends FieldPath<TFieldValues>>(
    name: TName,
  ) => FFormFieldBundle<TFieldValues, TName, TTransformedValues, TSubmitOutput>
  button: <TType extends FormButtonType>(
    type: TType,
  ) => FFormButtonBundle<TType, TFieldValues, TTransformedValues, TSubmitOutput>

  // Grouped settings (output)
  settings: FormSettings

  // Escape hatch to the raw RHF return value (unstable outer, stable methods)
  rhf: UseFormReturn<TFieldValues, any, TTransformedValues>

  // Internal helpers consumed by `useFValues`.
  // Underscore-prefixed to signal "not for app code". Stable identity.
  _parseValues: (values: TFieldValues) => TTransformedValues | undefined
  _lastValuesValidRef: { current: ValuesValidSnapshot<TFieldValues, TTransformedValues> | undefined }
  // Internal alert store accessors consumed by `useFFormAlert` via `useSyncExternalStore`.
  _alertSubscribe: (listener: () => void) => () => void
  _alertGet: () => FFormAlert | null

  Infer: {
    FieldValues: TFieldValues
    TransformedValues: TTransformedValues
    SubmitOutput: TSubmitOutput
  }
}

type LiveBag<TFieldValues extends FieldValues, TTransformedValues extends FieldValues, TSubmitOutput> = {
  id: string | undefined
  rhf: UseFormReturn<TFieldValues, any, TTransformedValues>
  settings: FormSettings
  handleSubmit: (event?: React.BaseSyntheticEvent) => Promise<void>
  submit: () => void
  send: (values: TFieldValues) => Promise<TSubmitOutput>
  clear: (defaultValues?: DefaultValues<TFieldValues>) => void
  parseValues: (values: TFieldValues) => TTransformedValues | undefined
  setAlert: (alert: FFormAlert | null) => void
}

const RHF_PASSTHROUGH_KEYS = [
  'control',
  'register',
  'getValues',
  'setValue',
  'setError',
  'clearErrors',
  'trigger',
  'getFieldState',
  'resetField',
  'unregister',
  'setFocus',
  'subscribe',
  'watch',
  'reset',
  'formState',
] as const

export const useFForm = <
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>(
  props: UseFFormProps<TFieldValues, TTransformedValues, TSubmitOutput>,
): UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput> => {
  const {
    id,
    onSubmit,
    onValidationError,
    onSuccess,
    onSettled,
    onSubmitError,
    schema,
    mode = 'onSubmit',
    reValidateMode = 'onChange',
    submitOnMount = false,
    submitOnChange = false,
    toastOnSuccess = false,
    toastOnValidationError = true,
    toastOnSubmitError = true,
    alertOnSuccess = false,
    alertOnValidationError = false,
    alertOnSubmitError = false,
    alertOnSubmitErrorDuration = Infinity,
    alertOnValidationErrorDuration = Infinity,
    alertOnSuccessDuration = 5000,
    buttonDisabledOnFormInvalid = false,
    buttonDisabledOnFormPristine = false,
    fieldDisabledOnFormSubmitting: fieldDisabledOnFormSubmittingProvided,
    clearFormOnSuccess: clearFormOnSuccessProvided,
    defaultValues: defaultValuesProvided,
    use,
    ...restProps
  } = props

  // `submitOnChange` flips a couple of defaults: clearing values after a successful
  // submit would loop the auto-submit, and disabling fields while submitting would
  // disrupt the user mid-typing. Explicit user-provided values always win.
  const submitOnChangeEnabled = submitOnChange !== false
  const clearFormOnSuccess =
    clearFormOnSuccessProvided !== undefined ? clearFormOnSuccessProvided : !submitOnChangeEnabled
  const fieldDisabledOnFormSubmitting = fieldDisabledOnFormSubmittingProvided ?? !submitOnChangeEnabled

  const resolver = useMemo(
    () => (schema ? zodResolver(schema, undefined, { mode: 'sync' }) : restProps.resolver),
    [schema, restProps.resolver],
  )

  const rhf = useForm<TFieldValues, any, TTransformedValues>({
    ...restProps,
    defaultValues: defaultValuesProvided,
    mode,
    reValidateMode,
    resolver,
  })

  const parseValues = useCallback(
    (valuesOriginal: TFieldValues) => {
      if (schema) {
        const result = schema.safeParse(valuesOriginal)
        return result.success ? result.data : undefined
      }
      const result = resolver?.(valuesOriginal, undefined, {
        criteriaMode: 'all',
        fields: {},
        shouldUseNativeValidation: false,
      })
      if (isPromiseLike(result)) {
        throw new Error('Async form parsing is not supported')
      }
      if (result?.errors && Object.keys(result.errors).length > 0) {
        return
      }
      return (!result ? valuesOriginal : result.values) as TTransformedValues
    },
    [resolver, schema],
  )

  const lastValuesValidRef = useRef<ValuesValidSnapshot<TFieldValues, TTransformedValues> | undefined>(undefined)

  // Alert store. The active alert is held in a mutable ref + listeners Set so that
  // `<FAlert />` (and any other subscriber) can use `useSyncExternalStore` for
  // reactive reads without forcing a re-render of the form-owning component.
  const alertStateRef = useRef<{
    alert: FFormAlert | null
    timeoutId: ReturnType<typeof setTimeout> | null
    listeners: Set<() => void>
  }>({ alert: null, timeoutId: null, listeners: new Set() })

  const notifyAlertListeners = () => {
    for (const listener of alertStateRef.current.listeners) {
      listener()
    }
  }

  const settings = useMemo<FormSettings>(
    () => ({
      buttonDisabledOnFormInvalid,
      buttonDisabledOnFormPristine,
      fieldDisabledOnFormSubmitting,
    }),
    [buttonDisabledOnFormInvalid, buttonDisabledOnFormPristine, fieldDisabledOnFormSubmitting],
  )

  // Hold the latest closures/refs so the stable handle below can delegate without changing identity.
  const liveRef = useRef<LiveBag<TFieldValues, TTransformedValues, TSubmitOutput>>(
    null as unknown as LiveBag<TFieldValues, TTransformedValues, TSubmitOutput>,
  )

  const resolveSuccessMessage = (
    value: NonNullable<UseFFormProps<TFieldValues, TTransformedValues, TSubmitOutput>['toastOnSuccess']>,
    out: TSubmitOutput,
  ): string => (typeof value === 'function' ? value(out) : typeof value === 'string' ? value : 'Success')

  const resolveSubmitErrorMessage = (
    value: NonNullable<UseFFormProps<TFieldValues, TTransformedValues, TSubmitOutput>['toastOnSubmitError']>,
    error: AppError,
  ): string => (typeof value === 'function' ? value(error) : typeof value === 'string' ? value : error.message)

  const resolveValidationErrorMessage = (
    value: NonNullable<UseFFormProps<TFieldValues, TTransformedValues, TSubmitOutput>['toastOnValidationError']>,
    errors: FieldErrors<TFieldValues>,
  ): string =>
    typeof value === 'function'
      ? value(errors)
      : typeof value === 'string'
        ? value
        : 'Some fields are invalid, please check your input'

  const setAlertImpl = (next: FFormAlert | null) => {
    const state = alertStateRef.current
    if (state.timeoutId !== null) {
      clearTimeout(state.timeoutId)
      state.timeoutId = null
    }
    state.alert = next
    if (next) {
      const duration =
        next.kind === 'success'
          ? alertOnSuccessDuration
          : next.kind === 'validationError'
            ? alertOnValidationErrorDuration
            : alertOnSubmitErrorDuration
      if (Number.isFinite(duration) && duration > 0) {
        state.timeoutId = setTimeout(() => {
          state.alert = null
          state.timeoutId = null
          notifyAlertListeners()
        }, duration)
      }
    }
    notifyAlertListeners()
  }

  const runValidationError = (errors: FieldErrors<TFieldValues>) => {
    onValidationError?.(errors)
    if (toastOnValidationError) {
      toast.error(resolveValidationErrorMessage(toastOnValidationError, errors))
    }
    if (alertOnValidationError) {
      setAlertImpl({
        kind: 'validationError',
        message: resolveValidationErrorMessage(alertOnValidationError, errors),
      })
    }
  }

  const clearImpl = (defaultValues?: DefaultValues<TFieldValues> | null) => {
    rhf.reset(
      defaultValues === null ? ({} as never) : defaultValues || (defaultValuesProvided as DefaultValues<TFieldValues>),
      {
        keepFieldsRef: true,
        keepIsSubmitSuccessful: true,
        keepIsSubmitted: true,
        keepSubmitCount: true,
      },
    )
  }

  const runSubmitPipeline = async (
    inputParsed: TTransformedValues,
    inputOriginal: TFieldValues,
    event?: React.BaseSyntheticEvent,
  ) => {
    let out: TSubmitOutput
    try {
      out = (await onSubmit?.(inputParsed, inputOriginal, event)) as TSubmitOutput
      await onSuccess?.(out, inputParsed, inputOriginal)
      if (clearFormOnSuccess !== false) {
        clearImpl(clearFormOnSuccess === null ? null : undefined)
      }
      if (toastOnSuccess) {
        toast.success(resolveSuccessMessage(toastOnSuccess, out))
      }
      if (alertOnSuccess) {
        setAlertImpl({ kind: 'success', message: resolveSuccessMessage(alertOnSuccess, out) })
      }
    } catch (err) {
      const e0 = AppError.from(err)
      onSubmitError?.(e0)
      if (toastOnSubmitError) {
        toast.error(resolveSubmitErrorMessage(toastOnSubmitError, e0))
      }
      if (alertOnSubmitError) {
        setAlertImpl({ kind: 'submitError', message: resolveSubmitErrorMessage(alertOnSubmitError, e0) })
      }
      onSettled?.({ status: 'error', error: e0 })
      throw e0
    }
    onSettled?.({ status: 'success', submitOutput: out, inputParsed, inputOriginal })
    return out
  }

  const handleSubmitImpl = async (event?: React.BaseSyntheticEvent) => {
    await rhf.handleSubmit(async (parsed, ev) => {
      const original = rhf.getValues()
      try {
        await runSubmitPipeline(parsed, original, ev)
      } catch (err) {
        l.error(err)
      }
    }, runValidationError)(event)
  }

  const submitImpl = () => {
    void handleSubmitImpl()
  }

  const sendImpl = async (inputOriginal: TFieldValues): Promise<TSubmitOutput> => {
    const inputParseResult = await resolver?.(inputOriginal, undefined, {
      criteriaMode: 'all',
      fields: {},
      shouldUseNativeValidation: false,
    })
    if (inputParseResult?.errors && Object.keys(inputParseResult.errors).length > 0) {
      runValidationError(inputParseResult.errors as FieldErrors<TFieldValues>)
      throw new Error('Input is invalid, please check your input', { cause: inputParseResult.errors })
    }
    const inputParsed = (!inputParseResult ? inputOriginal : inputParseResult.values) as TTransformedValues
    return await runSubmitPipeline(inputParsed, inputOriginal)
  }

  // Intentionally write to the live ref during render so that getters on the
  // stable handle below always see the latest closures and the current `rhf`.
  // Without this, children rendered in the same pass would observe stale state.
  liveRef.current = {
    id,
    rhf,
    settings,
    handleSubmit: handleSubmitImpl,
    submit: submitImpl,
    send: sendImpl,
    clear: clearImpl,
    parseValues,
    setAlert: setAlertImpl,
  }

  // Build the public FForm once. From here on, its identity never changes.
  const fFormRef = useRef<UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput> | null>(null)
  if (fFormRef.current == null) {
    const stable = {} as UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput>

    const settingsProxy = new Proxy({} as FormSettings, {
      get: (_target, key) => (liveRef.current.settings as Record<string, unknown>)[key as string],
      has: (_target, key) => key in liveRef.current.settings,
      ownKeys: () => Reflect.ownKeys(liveRef.current.settings),
      getOwnPropertyDescriptor: (_target, key) => {
        if (!(key in liveRef.current.settings)) {
          return undefined
        }
        return {
          enumerable: true,
          configurable: true,
          writable: false,
          value: (liveRef.current.settings as Record<string, unknown>)[key as string],
        }
      },
    })

    for (const key of RHF_PASSTHROUGH_KEYS) {
      Object.defineProperty(stable, key, {
        enumerable: true,
        configurable: false,
        get: () => (liveRef.current.rhf as unknown as Record<string, unknown>)[key],
      })
    }
    Object.defineProperty(stable, 'id', {
      enumerable: true,
      configurable: false,
      get: () => liveRef.current.id,
    })
    Object.defineProperty(stable, 'rhf', {
      enumerable: true,
      configurable: false,
      get: () => liveRef.current.rhf,
    })
    Object.defineProperty(stable, 'settings', {
      enumerable: true,
      configurable: false,
      value: settingsProxy,
      writable: false,
    })

    // eslint-disable-next-line @typescript-eslint/promise-function-async
    stable.handleSubmit = (event) => liveRef.current.handleSubmit(event)
    stable.submit = () => liveRef.current.submit()
    // eslint-disable-next-line @typescript-eslint/promise-function-async
    stable.send = (values) => liveRef.current.send(values)
    stable.clear = (defaults) => liveRef.current.clear(defaults)
    stable.setAlert = (next) => liveRef.current.setAlert(next)
    Object.defineProperty(stable, 'alert', {
      enumerable: true,
      configurable: false,
      get: () => alertStateRef.current.alert,
    })

    // Bind the standalone hooks to this form. The form?: prop is injected so consumers can omit it.
    // Both shapes — `fn(props)` and `fn(props, callback)` (plus the `fn(callback)` shorthand) — must
    // forward through, otherwise the callback-subscription overload is silently dropped.
    const bindHook =
      <THook extends (...args: any[]) => any>(hook: THook) =>
      (propsOrCallback?: any, callbackArg?: any) => {
        if (typeof propsOrCallback === 'function') {
          return (hook as (...a: any[]) => any)({ form: stable }, propsOrCallback)
        }
        const merged = { ...(propsOrCallback ?? {}), form: stable }
        return callbackArg === undefined
          ? (hook as (...a: any[]) => any)(merged)
          : (hook as (...a: any[]) => any)(merged, callbackArg)
      }

    stable.useValues = bindHook(useFValues as unknown as (...a: any[]) => any) as UseFFormReturn<
      TFieldValues,
      TTransformedValues,
      TSubmitOutput
    >['useValues']
    stable.useSubscribe = bindHook(useFFormSubscribe as unknown as (...a: any[]) => any) as UseFFormReturn<
      TFieldValues,
      TTransformedValues,
      TSubmitOutput
    >['useSubscribe']
    stable.useAlert = bindHook(useFFormAlert as unknown as (...a: any[]) => any) as UseFFormReturn<
      TFieldValues,
      TTransformedValues,
      TSubmitOutput
    >['useAlert']

    stable.field = (<TName extends FieldPath<TFieldValues>>(name: TName) => ({
      form: stable,
      name,
    })) as UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput>['field']

    stable.button = (<TType extends FormButtonType>(type: TType) => ({
      form: stable,
      type,
    })) as UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput>['button']

    Object.defineProperty(stable, '_parseValues', {
      enumerable: false,
      configurable: false,
      value: (values: TFieldValues) => liveRef.current.parseValues(values),
      writable: false,
    })
    Object.defineProperty(stable, '_lastValuesValidRef', {
      enumerable: false,
      configurable: false,
      value: lastValuesValidRef,
      writable: false,
    })
    Object.defineProperty(stable, '_alertSubscribe', {
      enumerable: false,
      configurable: false,
      value: (listener: () => void) => {
        alertStateRef.current.listeners.add(listener)
        return () => {
          alertStateRef.current.listeners.delete(listener)
        }
      },
      writable: false,
    })
    Object.defineProperty(stable, '_alertGet', {
      enumerable: false,
      configurable: false,
      value: () => alertStateRef.current.alert,
      writable: false,
    })

    fFormRef.current = stable
  }

  // Keep `lastValuesValidRef.current` up to date so `useFValues` can fall back to the
  // last-known-valid snapshot.
  useEffect(() => {
    const seed = parseValues(rhf.getValues())
    if (seed !== undefined) {
      lastValuesValidRef.current = { parsed: seed, original: rhf.getValues() }
    }
    const unsubscribe = rhf.subscribe({
      formState: { values: true },
      callback: ({ values }) => {
        const next = parseValues(values)
        if (next !== undefined) {
          lastValuesValidRef.current = { parsed: next, original: values }
        }
      },
    })
    return unsubscribe
  }, [parseValues, rhf])

  useEffect(() => {
    if (submitOnMount) {
      liveRef.current.submit()
    }
    // Empty deps for the boolean case = one submit per form instance per mount.
    // Each `useFForm` owns this effect, so independent forms in sibling components
    // each fire their own submit on their own mount. The array overload re-fires
    // when its members change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...(Array.isArray(submitOnMount) ? submitOnMount : [])])

  // Validation alerts auto-dismiss once all validation errors are dismissed — the alert
  // was caused by those errors, so it loses its meaning the moment the form goes clean.
  // Other alert kinds (success / submit error) are unaffected.
  useEffect(() => {
    const unsubscribe = rhf.subscribe({
      formState: { errors: true },
      callback: ({ errors }) => {
        const current = alertStateRef.current.alert
        if (current?.kind === 'validationError' && (!errors || Object.keys(errors).length === 0)) {
          liveRef.current.setAlert(null)
        }
      },
    })
    return unsubscribe
  }, [rhf])

  // Final cleanup: drop any pending auto-dismiss timer when the host unmounts.
  // Capture the ref's holder up-front: the object identity is stable for the
  // lifetime of this hook, so the cleanup never reads a stale shape.
  useEffect(() => {
    const state = alertStateRef.current
    return () => {
      if (state.timeoutId !== null) {
        clearTimeout(state.timeoutId)
        state.timeoutId = null
      }
    }
  }, [])

  const submitOnChangeDebounceMs =
    typeof submitOnChange === 'number' ? submitOnChange : submitOnChange ? SUBMIT_ON_CHANGE_DEFAULT_DEBOUNCE_MS : null

  useEffect(() => {
    if (submitOnChangeDebounceMs === null) {
      return
    }
    let timeoutId: ReturnType<typeof setTimeout> | undefined
    const unsubscribe = rhf.subscribe({
      formState: { values: true },
      callback: ({ values }) => {
        if (timeoutId !== undefined) {
          clearTimeout(timeoutId)
        }
        // Skip invalid states silently — no submit, no validation toast.
        // We re-check inside the timeout too so a value that goes invalid during
        // the debounce window doesn't slip through.
        if (liveRef.current.parseValues(values as TFieldValues) === undefined) {
          return
        }
        timeoutId = setTimeout(() => {
          const latest = liveRef.current.rhf.getValues()
          if (liveRef.current.parseValues(latest) === undefined) {
            return
          }
          liveRef.current.submit()
        }, submitOnChangeDebounceMs)
      },
    })
    return () => {
      if (timeoutId !== undefined) {
        clearTimeout(timeoutId)
      }
      unsubscribe()
    }
  }, [submitOnChangeDebounceMs, rhf])

  // Run user-supplied setup hooks against the stable form handle. Must run at a fixed position
  // every render — `use` is expected to be either consistently defined or consistently undefined
  // for the lifetime of the hosting component.
  use?.(fFormRef.current)

  return fFormRef.current
}
