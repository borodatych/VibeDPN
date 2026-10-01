import type { ApplyView } from '@/features/uplinks/shared'
import { CORE_API_PREFIX } from '@/modules/core/prefix'

/** An archive of `backups/` (core/vibedpn/api/models.py: ArchiveView). */
export type Archive = { name: string; size: number; created_at: number }

/** Core's `GET /backups` (core/vibedpn/api/models.py: BackupsView). */
export type BackupsView = { archives: Archive[]; keep: number; backup: ApplyView; restore: ApplyView }

// core/vibedpn/api/backups.py MAX_RESTORE_BYTES: Bun refuses a bigger request body anyway
export const MAX_RESTORE_BYTES = 128 * 1024 * 1024

/** Where the browser takes an archive from and sends one to: core through the session of the panel. */
export const archiveUrl = (name: string) => `${CORE_API_PREFIX}/backups/${encodeURIComponent(name)}`
export const RESTORE_UPLOAD_URL = `${CORE_API_PREFIX}/restore`

/**
 * Whether the box is busy with a backup or a restore: each stops it, so one at a time
 *
 * @tags backup
 */
export const busyWithArchives = (view: BackupsView): boolean => view.backup.pending || view.restore.pending

/**
 * Why a chosen file cannot be sent for a restore yet; `null` when it can. Only a hint: core reads the archive itself
 *
 * @tags backup
 */
export const uploadProblem = (file: { size: number }): 'empty' | 'size' | null => {
  if (file.size === 0) {
    return 'empty'
  }
  return file.size > MAX_RESTORE_BYTES ? 'size' : null
}
