import { AddForm } from '@/features/torrents/add'
import { DetailView } from '@/features/torrents/detail'
import { RemoveDialog } from '@/features/torrents/list'
import { TorrentsScreen } from '@/features/torrents/screen'
import type { TorrentDetail, TorrentList, TorrentSummary } from '@/features/torrents/shared'
import { baseStrings } from '@/modules/i18n/base'
import { LanguageContext } from '@/modules/i18n/use-t'
import { describe, expect, mock, test } from 'bun:test'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import type { ReactNode } from 'react'

const ru = JSON.parse(readFileSync(join(import.meta.dir, '../../../locales/ru.json'), 'utf8')) as Record<string, string>

const inRussian = (node: ReactNode) =>
  render(
    <LanguageContext.Provider value={{ language: 'ru', strings: { ...baseStrings, ...ru } }}>
      {node}
    </LanguageContext.Provider>,
  )

const torrent = (patch: Partial<TorrentSummary>): TorrentSummary => ({
  id: '7ad0393e3790590660678ef4e876a5248dcdad8d',
  name: 'ubuntu.iso',
  status: 'downloading',
  progress: 0.42,
  rate_down: 1048576,
  rate_up: 2048,
  eta: 3600,
  size: 4_800_000_000,
  ratio: 0.1,
  error: null,
  ...patch,
})

const noop = () => {}
const screenProps = { busyId: null, error: null, onAdd: noop, onOpen: noop, onToggle: noop, onRemove: noop }

describe('page «Torrents»', () => {
  test('a service that is off tells how to turn it on and shows the reason of core', () => {
    inRussian(<TorrentsScreen {...screenProps} off reason="Торрент-клиент выключен в config.yaml" list={null} />)
    expect(
      screen.getByText('Торрент-клиент выключен', { selector: '[data-slot=card-title], h2, h3, div' }),
    ).toBeTruthy()
    expect(screen.getByText(/sudo vibedpn torrents enable/)).toBeTruthy()
    expect(screen.getByText('Торрент-клиент выключен в config.yaml')).toBeTruthy()
  })

  test('an empty list invites to add the first torrent', () => {
    const onAdd = mock(() => {})
    const list: TorrentList = { torrents: [], rate_down: 0, rate_up: 0 }
    inRussian(<TorrentsScreen {...screenProps} off={false} reason={null} list={list} onAdd={onAdd} />)
    expect(screen.getByText('Торрентов пока нет')).toBeTruthy()
    act(() => {
      screen.getByRole('button', { name: 'Добавить торрент' }).click()
    })
    expect(onAdd).toHaveBeenCalledTimes(1)
  })

  test('the list shows each torrent with its numbers, and the filters narrow it', () => {
    const list: TorrentList = {
      torrents: [
        torrent({ id: 'a', name: 'ubuntu.iso' }),
        torrent({ id: 'b', name: 'debian.iso', status: 'seeding', progress: 1, eta: null }),
        torrent({ id: 'c', name: 'broken.iso', error: 'Tracker gave an error' }),
      ],
      rate_down: 1048576,
      rate_up: 2048,
    }
    inRussian(<TorrentsScreen {...screenProps} off={false} reason={null} list={list} />)
    expect(screen.getByText('ubuntu.iso')).toBeTruthy()
    expect(screen.getAllByText('1.0 MiB/s').length).toBeGreaterThan(0)
    expect(screen.getAllByText('1 ч 0 мин').length).toBe(2)
    expect(screen.getByText('Tracker gave an error')).toBeTruthy()
    // the same table serves a phone, which turns its rows to cards by data-label
    expect(screen.getAllByRole('progressbar').length).toBe(3)
    act(() => {
      screen.getByRole('button', { name: 'Раздаются · 1' }).click()
    })
    expect(screen.queryByText('ubuntu.iso')).toBeNull()
    expect(screen.getByText('debian.iso')).toBeTruthy()
    act(() => {
      screen.getByRole('button', { name: 'На паузе · 0' }).click()
    })
    expect(screen.getByText('Таких торрентов нет.')).toBeTruthy()
  })

  test('pause, start and remove of a row are the actions of that torrent', () => {
    const onToggle = mock(() => {})
    const onRemove = mock(() => {})
    const list: TorrentList = { torrents: [torrent({ name: 'ubuntu.iso' })], rate_down: 0, rate_up: 0 }
    inRussian(
      <TorrentsScreen {...screenProps} off={false} reason={null} list={list} onToggle={onToggle} onRemove={onRemove} />,
    )
    act(() => {
      screen.getByRole('button', { name: 'Приостановить' }).click()
      screen.getByRole('button', { name: 'Удалить' }).click()
    })
    expect(onToggle).toHaveBeenCalledTimes(1)
    expect(onRemove).toHaveBeenCalledTimes(1)
  })
})

describe('removing a torrent', () => {
  test('keeps the files unless the box is ticked, and says which it does on the button', () => {
    const onConfirm = mock((_deleteData: boolean) => {})
    inRussian(<RemoveDialog torrent={torrent({})} pending={false} error={null} onConfirm={onConfirm} onCancel={noop} />)
    const dialog = within(screen.getByRole('dialog'))
    act(() => {
      dialog.getByRole('button', { name: 'Удалить, файлы оставить' }).click()
    })
    expect(onConfirm).toHaveBeenLastCalledWith(false)
    act(() => {
      dialog.getByRole('checkbox').click()
    })
    act(() => {
      dialog.getByRole('button', { name: 'Удалить вместе с файлами' }).click()
    })
    expect(onConfirm).toHaveBeenLastCalledWith(true)
  })
})

describe('adding a torrent', () => {
  test('a magnet link is sent as it is typed, with the folder and the start choice', () => {
    const onSubmit = mock(() => {})
    inRussian(<AddForm pending={false} error={null} onSubmit={onSubmit} />)
    const submit = screen.getByRole('button', { name: 'Добавить' })
    expect(submit.hasAttribute('disabled')).toBe(true)
    fireEvent.change(screen.getByRole('textbox', { name: 'Магнет-ссылка' }), {
      target: { value: 'magnet:?xt=urn:btih:7ad0393e3790590660678ef4e876a5248dcdad8d' },
    })
    fireEvent.change(screen.getByLabelText(/Папка внутри загрузок/), { target: { value: 'films' } })
    expect(submit.hasAttribute('disabled')).toBe(false)
    act(() => {
      submit.click()
    })
    expect(onSubmit).toHaveBeenCalledWith({
      magnet: 'magnet:?xt=urn:btih:7ad0393e3790590660678ef4e876a5248dcdad8d',
      torrent: null,
      subdir: 'films',
      paused: false,
    })
  })

  test('a folder with a slash blocks the button and says why', () => {
    inRussian(<AddForm pending={false} error={null} onSubmit={noop} />)
    fireEvent.change(screen.getByRole('textbox', { name: 'Магнет-ссылка' }), {
      target: { value: 'magnet:?xt=urn:btih:7ad0393e3790590660678ef4e876a5248dcdad8d' },
    })
    fireEvent.change(screen.getByLabelText(/Папка внутри загрузок/), { target: { value: 'a/b' } })
    expect(screen.getByText(/Одно имя без косых черт/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Добавить' }).hasAttribute('disabled')).toBe(true)
  })
})

describe('an open torrent', () => {
  const detail: TorrentDetail = {
    ...torrent({}),
    download_dir: '/downloads/complete',
    files: [
      { index: 0, name: 'dir/a.mkv', size: 1000, done: 500, wanted: true, priority: 'normal' },
      { index: 1, name: 'dir/b.srt', size: 10, done: 0, wanted: false, priority: 'low' },
    ],
    peers: [
      { address: '203.0.113.5', client: 'qBittorrent 5.0', progress: 0.5, rate_down: 100, rate_up: 0, flags: 'TDE' },
    ],
    trackers: [],
  }

  test('a file is switched on and off alone, and «all files» switches them together', () => {
    const onFilesChange = mock((_change: unknown) => {})
    inRussian(<DetailView detail={detail} onFilesChange={onFilesChange} />)
    expect(screen.getByText('dir/a.mkv')).toBeTruthy()
    const boxes = screen.getAllByRole('checkbox')
    act(() => {
      boxes[2]?.click()
    })
    expect(onFilesChange).toHaveBeenLastCalledWith({ indices: [1], wanted: true, priority: null })
    act(() => {
      boxes[0]?.click()
    })
    expect(onFilesChange).toHaveBeenLastCalledWith({ indices: [0, 1], wanted: true, priority: null })
  })

  test('the tabs count peers and trackers, and a torrent without trackers says so', () => {
    inRussian(<DetailView detail={detail} onFilesChange={noop} />)
    expect(screen.getByRole('tab', { name: 'Пиры · 1' })).toBeTruthy()
    expect(screen.getByRole('tab', { name: 'Трекеры · 0' })).toBeTruthy()
  })
})
