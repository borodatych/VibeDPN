import type { ApplyView } from '@/features/uplinks/shared'

export type Verdict = 'ok' | 'warn' | 'fail'

/** One check of `vibedpn doctor` (core/vibedpn/api/models.py: CheckView). */
export type Check = { name: string; verdict: Verdict; detail: string; hint: string }

/** The report the host keeps (core/vibedpn/api/models.py: DoctorReportView). */
export type DoctorReport = { finished_at: number; network: boolean; checks: Check[] }

/** Core's `GET /doctor` (core/vibedpn/api/models.py: DoctorView). */
export type DoctorView = { report: DoctorReport | null; state: ApplyView }

const VERDICT_ORDER: Record<Verdict, number> = { fail: 0, warn: 1, ok: 2 }

/**
 * The checks that want attention first: failures, then warnings, each in the order doctor made them
 *
 * @tags doctor
 */
export const problemsFirst = (checks: Check[]): Check[] =>
  [...checks].sort((a, b) => VERDICT_ORDER[a.verdict] - VERDICT_ORDER[b.verdict])

/**
 * How many checks got each verdict
 *
 * @tags doctor
 */
export const countVerdicts = (checks: Check[]): Record<Verdict, number> => {
  const counts: Record<Verdict, number> = { ok: 0, warn: 0, fail: 0 }
  for (const check of checks) {
    counts[check.verdict] += 1
  }
  return counts
}
