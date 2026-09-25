/** How the last update asked in the panel ended (core `GET /update`, engine/update.py). */
export type UpdateResult = {
  ok: boolean
  message: string
  /** Short commits; empty when unknown */
  before: string
  after: string
  finished_at: number
}

/** The revision the box runs, an update in progress, and how the last one ended. */
export type UpdateView = {
  branch: string | null
  commit: string | null
  committed_at: string | null
  pending: boolean
  last: UpdateResult | null
}

/**
 * Whether the update asked at `askedAt` (unix seconds) has finished well
 *
 * Then the panel reloads: the page in the browser still runs the code of the old version
 */
export const updatedSince = (view: UpdateView, askedAt: number): boolean =>
  !view.pending && view.last !== null && view.last.ok && view.last.finished_at >= askedAt
