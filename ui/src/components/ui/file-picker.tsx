import { Button } from '@/components/ui/button'
import { useT } from '@/modules/i18n/use-t'
import { FileUpIcon } from 'lucide-react'
import { useRef, useState } from 'react'

/**
 * A file field that speaks the language of the panel: the browser's own `<input type="file">` names its button and
 * «no file chosen» in the language of the browser, whatever the panel shows
 *
 * The real input stays in the page, hidden, so `accept` and the file dialog are the browser's
 *
 * @tags ui
 */
export const FilePicker = ({
  accept,
  disabled,
  label,
  onPick,
}: {
  accept: string
  disabled?: boolean
  /** the name of the field for the reader of the screen: the button alone says only «Choose a file» */
  label: string
  onPick: (file: File | null) => void
}) => {
  const t = useT()
  const input = useRef<HTMLInputElement>(null)
  const [name, setName] = useState<string | null>(null)
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-3">
      <input
        ref={input}
        type="file"
        accept={accept}
        aria-label={label}
        className="sr-only"
        tabIndex={-1}
        disabled={disabled}
        onChange={(event) => {
          const file = event.target.files?.[0] ?? null
          setName(file?.name ?? null)
          onPick(file)
        }}
      />
      <Button
        type="button"
        variant="outline-secondary"
        size="sm"
        icon={FileUpIcon}
        disabled={disabled}
        aria-label={`${t('file.choose')}: ${label}`}
        onClick={() => input.current?.click()}
      >
        {t('file.choose')}
      </Button>
      <span className="min-w-0 truncate text-sm text-muted-foreground">{name ?? t('file.none')}</span>
    </div>
  )
}
