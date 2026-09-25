import * as React from 'react'
import { isValid } from 'date-fns'
import { CalendarIcon } from 'lucide-react'

import { Calendar } from '@/components/ui/calendar'
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from '@/components/ui/input-group'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useT } from '@/modules/i18n/use-t'
import { formatDate } from '@/utils/date'

const formatDatePickerValue = (date: Date | undefined) => {
  if (!date) {
    return ''
  }
  return formatDate(date, 'date')
}

export type XDatePickerProps = Omit<
  React.ComponentProps<typeof InputGroupInput>,
  'children' | 'value' | 'defaultValue' | 'onChange'
> & {
  value?: Date
  defaultValue?: Date
  onValueChange?: (date: Date | undefined) => void
  onInputChange?: React.ChangeEventHandler<HTMLInputElement>
  placeholder?: string
  inputGroupProps?: React.ComponentProps<typeof InputGroup>
  inputAddonProps?: React.ComponentProps<typeof InputGroupAddon>
  inputButtonProps?: React.ComponentProps<typeof InputGroupButton>
  popoverProps?: React.ComponentProps<typeof Popover>
  popoverContentProps?: React.ComponentProps<typeof PopoverContent>
  calendarProps?: Omit<
    React.ComponentProps<typeof Calendar>,
    'mode' | 'selected' | 'onSelect' | 'month' | 'onMonthChange'
  >
}

export const XDatePicker = React.forwardRef<HTMLInputElement, XDatePickerProps>(function XDatePicker(props, ref) {
  const isControlled = 'value' in props
  const {
    value,
    defaultValue,
    onValueChange,
    onInputChange,
    placeholder,
    inputGroupProps,
    inputAddonProps,
    inputButtonProps,
    popoverProps,
    popoverContentProps,
    calendarProps,
    onKeyDown,
    ...inputProps
  } = props
  const t = useT()
  const [open, setOpen] = React.useState(false)
  const [uncontrolledDate, setUncontrolledDate] = React.useState<Date | undefined>(defaultValue)
  const selectedDate = isControlled ? value : uncontrolledDate
  const [month, setMonth] = React.useState<Date | undefined>(selectedDate)
  const [inputValue, setInputValue] = React.useState(formatDatePickerValue(selectedDate))

  React.useEffect(() => {
    setInputValue(formatDatePickerValue(selectedDate))
    setMonth(selectedDate)
  }, [selectedDate])

  const setSelectedDate = React.useCallback(
    (nextDate: Date | undefined) => {
      if (!isControlled) {
        setUncontrolledDate(nextDate)
      }
      onValueChange?.(nextDate)
    },
    [isControlled, onValueChange],
  )

  return (
    <InputGroup {...inputGroupProps}>
      <InputGroupInput
        {...inputProps}
        ref={ref}
        value={inputValue}
        placeholder={placeholder ?? t('ui.datePicker.placeholder')}
        onChange={(event) => {
          onInputChange?.(event)
          const nextValue = event.target.value
          const nextDate = new Date(nextValue)

          setInputValue(nextValue)
          if (isValid(nextDate)) {
            setSelectedDate(nextDate)
            setMonth(nextDate)
          }
        }}
        onKeyDown={(event) => {
          onKeyDown?.(event)
          if (event.defaultPrevented) {
            return
          }
          if (event.key === 'ArrowDown') {
            event.preventDefault()
            setOpen(true)
          }
        }}
      />
      <InputGroupAddon align="inline-end" {...inputAddonProps}>
        <Popover open={open} onOpenChange={setOpen} {...popoverProps}>
          <PopoverTrigger asChild>
            <InputGroupButton
              id={inputProps.id ? `${inputProps.id}-date-picker` : undefined}
              variant="ghost"
              size="icon-xs"
              aria-label={t('ui.datePicker.select')}
              {...inputButtonProps}
            >
              <CalendarIcon />
              <span className="sr-only">{t('ui.datePicker.select')}</span>
            </InputGroupButton>
          </PopoverTrigger>
          <PopoverContent
            className="w-auto overflow-hidden p-0"
            align="end"
            alignOffset={-8}
            sideOffset={10}
            {...popoverContentProps}
          >
            <Calendar
              {...calendarProps}
              mode="single"
              selected={selectedDate}
              month={month}
              onMonthChange={setMonth}
              onSelect={(nextDate) => {
                setSelectedDate(nextDate)
                setInputValue(formatDatePickerValue(nextDate))
                setOpen(false)
              }}
            />
          </PopoverContent>
        </Popover>
      </InputGroupAddon>
    </InputGroup>
  )
})
