import type { AnyUseFFormReturn, FormButtonType } from '@/modules/form/core/hook'
import { Button } from '@/components/ui/button'
import type { DistributiveOmit } from '@/types'
import { forwardRef, useMemo, type ComponentProps, type MouseEvent } from 'react'
import { useFormState } from 'react-hook-form'
import { useFFormContext } from './context'

// DistributiveOmit (not Omit) so Button's discriminated link-prop union survives — see @/types.
export type FButtonProps = DistributiveOmit<ComponentProps<typeof Button>, 'type' | 'form'> & {
  type?: FormButtonType
  form?: AnyUseFFormReturn
}

export const useFButtonProps = ({
  form: formProvided,
  disabled: disabledProvided,
  loading: loadingProvided,
  onClick: onClickProvided,
  type: typeProvided = 'submit',
  ...props
}: FButtonProps) => {
  const form = useFFormContext({ form: formProvided })
  const { buttonDisabledOnFormInvalid, buttonDisabledOnFormPristine } = form.settings

  // RHF's `useFormState` is proxy-based: only the keys we actually destructure trigger re-renders.
  const { isValid, isDirty, isSubmitting } = useFormState({ control: form.control })
  const isSubmitLikeButton = typeProvided === 'submit' || typeProvided === 'send'
  const disabledByFormState =
    isSubmitLikeButton && ((buttonDisabledOnFormInvalid && !isValid) || (buttonDisabledOnFormPristine && !isDirty))
  const disabled = disabledProvided || disabledByFormState
  const loading = isSubmitting || loadingProvided
  const type: ComponentProps<typeof Button>['type'] = typeProvided === 'submit' ? 'submit' : 'button'
  const onClick = useMemo(() => {
    const formAction =
      typeProvided === 'send'
        ? form.submit
        : typeProvided === 'reset'
          ? () => form.reset()
          : typeProvided === 'clear'
            ? () => form.clear()
            : undefined
    if (!formAction && !onClickProvided) {
      return undefined
    }
    return (event: MouseEvent<HTMLButtonElement>) => {
      formAction?.()
      onClickProvided?.(event)
    }
  }, [typeProvided, form, onClickProvided])
  return {
    disabled,
    loading,
    type,
    onClick,
    ...props,
  }
}

export const FButton = forwardRef<HTMLButtonElement, FButtonProps>((props, ref) => {
  const fButtonProps = useFButtonProps(props)

  return <Button {...fButtonProps} ref={ref} />
})
FButton.displayName = 'FButton'
