import { Button } from '@/components/ui/button'
import { baseStrings } from '@/modules/i18n/base'
import { LanguageContext } from '@/modules/i18n/use-t'
import { describe, expect, mock, test } from 'bun:test'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { act, render, screen } from '@testing-library/react'

const ru = JSON.parse(readFileSync(join(import.meta.dir, '../../../locales/ru.json'), 'utf8')) as Record<string, string>

const renderConfirm = (onClick: () => void) =>
  render(
    <LanguageContext.Provider value={{ language: 'ru', strings: { ...baseStrings, ...ru } }}>
      <Button confirm="Обновить?" onClick={onClick}>
        Обновить
      </Button>
    </LanguageContext.Provider>,
  )

describe('Button confirm', () => {
  test('asks in the language of the panel and runs the action only on its yes', () => {
    const onClick = mock(() => {})
    renderConfirm(onClick)
    act(() => {
      screen.getByText('Обновить').click()
    })
    expect(onClick).not.toHaveBeenCalled()
    expect(screen.getByText('Нет')).toBeTruthy()
    act(() => {
      screen.getByText('Да').click()
    })
    expect(onClick).toHaveBeenCalledTimes(1)
  })
})
