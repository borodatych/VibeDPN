import { Textarea } from '@/components/ui/textarea'
import type { WithFFieldUncontrolledProps } from '@/modules/form/core/field'
import { FFieldUncontrolled, splitFFieldUncontrolledProps } from '@/modules/form/core/field'
import { type FieldPath, type FieldValues } from 'react-hook-form'

/**
 * Form-bound multiline textarea for FForm.
 *
 * @example
 *   ;<FTextarea name="bio" label="Bio" />
 *
 * @tags form, fields
 */
export function FTextarea<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
  TTransformedValues extends FieldValues = TFieldValues,
  TSubmitOutput = void,
>(
  props: WithFFieldUncontrolledProps<
    React.ComponentProps<typeof Textarea>,
    TFieldValues,
    TName,
    TTransformedValues,
    TSubmitOutput
  > & { textareaProps?: React.ComponentProps<typeof Textarea> },
) {
  const {
    uncontrolledProps,
    rest: { textareaProps, ...restTextareaProps },
  } = splitFFieldUncontrolledProps(props)
  return (
    <FFieldUncontrolled
      {...uncontrolledProps}
      render={({ id, invalid, disabled, initialValue, register }) => {
        return (
          <Textarea
            {...restTextareaProps}
            {...textareaProps}
            {...register()}
            defaultValue={initialValue}
            id={id}
            aria-invalid={invalid}
            disabled={disabled}
          />
        )
      }}
    />
  )
}
