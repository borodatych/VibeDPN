import {
  archiveUrl,
  busyWithArchives,
  MAX_RESTORE_BYTES,
  uploadProblem,
  type BackupsView,
} from '@/features/backup/shared'
import { describe, expect, test } from 'bun:test'

const idle = { pending: false, ok: null, message: '', finished_at: null }

const view = (patch: Partial<BackupsView> = {}): BackupsView => ({
  archives: [],
  keep: 10,
  backup: idle,
  restore: idle,
  ...patch,
})

describe('backups', () => {
  test('one backup or restore at a time', () => {
    expect(busyWithArchives(view())).toBe(false)
    expect(busyWithArchives(view({ backup: { ...idle, pending: true } }))).toBe(true)
    expect(busyWithArchives(view({ restore: { ...idle, pending: true } }))).toBe(true)
  })

  test('a file for a restore is not empty and fits what the panel carries', () => {
    expect(uploadProblem({ size: 0 })).toBe('empty')
    expect(uploadProblem({ size: MAX_RESTORE_BYTES })).toBeNull()
    expect(uploadProblem({ size: MAX_RESTORE_BYTES + 1 })).toBe('size')
  })

  test('an archive is fetched from core through the panel by its name', () => {
    expect(archiveUrl('vibedpn-20261001-120000.tar.gz')).toBe('/api/core/backups/vibedpn-20261001-120000.tar.gz')
  })
})
