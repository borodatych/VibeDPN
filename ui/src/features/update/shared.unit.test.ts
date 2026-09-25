import { updatedSince, type UpdateView } from '@/features/update/shared'
import { describe, expect, test } from 'bun:test'

const view = (patch: Partial<UpdateView> = {}): UpdateView => ({
  branch: 'next',
  commit: 'def5678',
  committed_at: '2026-09-25T10:00:00+03:00',
  pending: false,
  last: { ok: true, message: 'updated', before: 'abc1234', after: 'def5678', finished_at: 200 },
  ...patch,
})

describe('updatedSince', () => {
  test('the update asked here ended well: the page reloads into the new version', () => {
    expect(updatedSince(view(), 100)).toBe(true)
  })

  test('not while it runs, not after a failure, not for an update that ended before the ask', () => {
    expect(updatedSince(view({ pending: true }), 100)).toBe(false)
    expect(updatedSince(view({ last: { ...view().last!, ok: false } }), 100)).toBe(false)
    expect(updatedSince(view(), 300)).toBe(false)
    expect(updatedSince(view({ last: null }), 100)).toBe(false)
  })
})
