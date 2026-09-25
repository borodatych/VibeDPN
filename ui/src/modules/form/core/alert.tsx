import { Alert, AlertAction, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { useT } from '@/modules/i18n/use-t'
import { cn } from '@/utils'
import { XIcon } from 'lucide-react'
import { useCallback, useState, useSyncExternalStore, type ReactNode } from 'react'
import type { FieldValues } from 'react-hook-form'
import { useFFormContext } from './context'
import type { FFormAlert, FFormAlertKind, UseFFormAlertBoundProps, UseFFormReturn } from './hook'

// ---------- ui ----------

export type XAlertVariant = 'default' | 'destructive' | 'success' | 'warning' | 'info'

export type XAlertProps = {
  variant?: XAlertVariant
  title?: ReactNode
  description?: ReactNode
  dismissible?: boolean
  onDismiss?: () => void
  dismissed?: boolean
  className?: string
  /** Custom body. When provided, replaces the default `title` / `description` block. */
  children?: ReactNode
}

export const XAlert = ({
  variant = 'default',
  title,
  description,
  dismissible,
  onDismiss: onDismissProvided,
  dismissed: dismissedProvided,
  className,
  children,
}: XAlertProps) => {
  const dismissControlled = dismissedProvided !== undefined
  const t = useT()
  const [dismissedInternal, setDismissedInternal] = useState(false)
  const onDismiss = useCallback(() => {
    onDismissProvided?.()
    if (!dismissControlled) {
      setDismissedInternal(true)
    }
  }, [onDismissProvided, setDismissedInternal, dismissControlled])
  return (
    <Alert
      variant={variant}
      className={cn(
        className,
        'not-first:mt-buttons-gap-lg not-last:mb-buttons-gap-lg',
        dismissedInternal && !dismissControlled && 'hidden',
      )}
    >
      {children ?? (
        <>
          {!!title && <AlertTitle>{title}</AlertTitle>}
          {!!description && <AlertDescription>{description}</AlertDescription>}
        </>
      )}
      {!!dismissible && (
        <AlertAction>
          <Button type="button" variant="ghost" size="icon-sm" onClick={onDismiss}>
            <XIcon />
            <span className="sr-only">{t('ui.dismiss')}</span>
          </Button>
        </AlertAction>
      )}
    </Alert>
  )
}
XAlert.displayName = 'XAlert'

// ---------- Standalone hook ----------

export type UseFFormAlertProps<
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = UseFFormAlertBoundProps & {
  /** Explicit form handle that wins over the surrounding `<FFormProvider>`. */
  form?: UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput>
}

/**
 * Subscribe to the active alert on a form. The form is taken from context unless an explicit `form` prop is provided.
 * Filter the result to specific alert kinds via `kind` — when the active alert doesn't match, the hook returns `null`
 * so the consumer can render nothing.
 *
 * Backed by `useSyncExternalStore`, so only components that read the alert are re-rendered when it changes.
 */
export const useFFormAlert = <
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>(
  props: UseFFormAlertProps<TFieldValues, TTransformedValues, TSubmitOutput> = {},
): FFormAlert | null => {
  const form = useFFormContext<TFieldValues, TTransformedValues, TSubmitOutput>({ form: props.form })
  const alert = useSyncExternalStore(form._alertSubscribe, form._alertGet, form._alertGet)
  if (alert && props.kind !== undefined) {
    const kinds = Array.isArray(props.kind) ? props.kind : [props.kind]
    if (!kinds.includes(alert.kind)) {
      return null
    }
  }
  return alert
}

// ---------- FAlert component ----------

export type FAlertProps<
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
> = Omit<XAlertProps, 'variant' | 'title' | 'description' | 'children' | 'onDismiss'> & {
  /** Explicit form handle that wins over context. */
  form?: UseFFormReturn<TFieldValues, TTransformedValues, TSubmitOutput>
  /** Restrict the alert to one or more kinds — others are silently ignored. */
  kind?: FFormAlertKind | FFormAlertKind[]
  /** Override the title; defaults to the alert message. */
  title?: ReactNode | ((alert: FFormAlert) => ReactNode)
  /** Optional description below the title. */
  description?: ReactNode | ((alert: FFormAlert) => ReactNode)
  /** Custom renderer; when provided, replaces the default `<Alert>` body. */
  children?: ReactNode | ((alert: FFormAlert) => ReactNode)
}

/**
 * Renders the active form alert in the styled `XAlert`. Returns `null` when no alert is active (or when `kind` filters
 * it out). Drop it anywhere inside an `<FForm>` — typically just above the submit button.
 */
export const FAlert = <
  TFieldValues extends FieldValues = FieldValues,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>({
  form: formProvided,
  kind,
  className,
  dismissible,
  title,
  description,
  children,
}: FAlertProps<TFieldValues, TTransformedValues, TSubmitOutput>) => {
  const form = useFFormContext<TFieldValues, TTransformedValues, TSubmitOutput>({ form: formProvided })
  const alert = useFFormAlert<TFieldValues, TTransformedValues, TSubmitOutput>({ form, kind })
  if (!alert) {
    return null
  }
  const variant: XAlertVariant = alert.kind === 'success' ? 'success' : 'destructive'
  const renderedTitle = typeof title === 'function' ? title(alert) : (title ?? alert.message)
  const renderedDescription = typeof description === 'function' ? description(alert) : description
  const renderedChildren = typeof children === 'function' ? children(alert) : children
  return (
    <XAlert
      variant={variant}
      title={renderedTitle}
      description={renderedDescription}
      dismissible={dismissible}
      onDismiss={() => form.setAlert(null)}
      dismissed={!alert}
      className={className}
    >
      {renderedChildren}
    </XAlert>
  )
}
FAlert.displayName = 'FAlert'
