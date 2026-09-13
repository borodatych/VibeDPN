#!/usr/bin/env bun
/* eslint-disable no-console -- standalone provisioning script, runs outside the app runtime */

/**
 * Axiom as code: the datasets + `props` map field, the email notifier, the monitors, and the dashboards. Idempotent —
 * matched by name, so re-running updates in place. Uses the ADVANCED token (`AXIOM_TOKEN_ROOT`) the app never reads;
 * `bun run axiom:provision` sources `.env.agents` for it and `ALERT_EMAILS`. Edit the set below and re-run.
 *
 * @tags axiom, setup, script
 * @related axiom, heartbeatWorker
 */

import { z } from 'zod'

// eslint-disable-next-line no-restricted-properties -- provisioning script: these live in .env.agents, never in the app env
const parsed = z.object({ AXIOM_TOKEN_ROOT: z.string().min(1), ALERT_EMAILS: z.string().min(1) }).safeParse(process.env)
if (!parsed.success) {
  console.error('[axiom] AXIOM_TOKEN_ROOT + ALERT_EMAILS required in .env.agents. Run via `bun run axiom:provision`.')
  process.exit(1)
}
const token = parsed.data.AXIOM_TOKEN_ROOT
const emails = parsed.data.ALERT_EMAILS.split(',')
  .map((email) => email.trim())
  .filter(Boolean)

const LOGS = 'logs'
const METRICS = 'metrics'

const api = async (method: string, path: string, body?: unknown): Promise<unknown> => {
  const response = await fetch(`https://api.axiom.co/v2${path}`, {
    method,
    headers: { authorization: `Bearer ${token}`, 'content-type': 'application/json' },
    ...(body ? { body: JSON.stringify(body) } : {}),
  })
  if (!response.ok) {
    throw new Error(`[axiom] ${method} ${path} → ${response.status} ${await response.text()}`)
  }
  return response.status === 204 ? undefined : ((await response.json()) as unknown)
}

// Upsert by name: list, match on name, then PUT the existing one or POST a new one.
const upsert = async (resource: 'notifiers' | 'monitors', name: string, body: Record<string, unknown>) => {
  const existing = ((await api('GET', `/${resource}`)) ?? []) as Array<{ id: string; name: string }>
  const found = existing.find((item) => item.name === name)
  if (found) {
    await api('PUT', `/${resource}/${found.id}`, { ...body, name })
    console.log(`[axiom] updated ${resource.slice(0, -1)} "${name}"`)
    return found.id
  }
  const created = (await api('POST', `/${resource}`, { ...body, name })) as { id: string }
  console.log(`[axiom] created ${resource.slice(0, -1)} "${name}"`)
  return created.id
}

// --- Datasets + the `props` map field (so unbounded log keys don't hit the 256-field cap) ---
const datasets = ((await api('GET', '/datasets')) ?? []) as Array<{ name: string }>
for (const [name, description] of [
  [LOGS, 'Application logs'],
  [METRICS, 'Application metrics'],
] as const) {
  if (!datasets.some((dataset) => dataset.name === name)) {
    await api('POST', '/datasets', { name, description })
    console.log(`[axiom] created dataset "${name}"`)
  }
}
await api('PUT', `/datasets/${LOGS}/mapfields`, ['props'])
console.log(`[axiom] set map field props on "${LOGS}"`)

// --- Notifier (email) ---
const notifierId = await upsert('notifiers', 'Email', { properties: { email: { emails } } })

// --- Monitors --- one aggregation per query (a single numeric column) so the threshold compares against that value.
// `prod` only — dev shares the datasets but must never page.
type MonitorDef = {
  name: string
  description: string
  apl: string
  operator: 'Above' | 'Below'
  threshold: number
  rangeMinutes: number
  alertOnNoData?: boolean
}

const monitors: MonitorDef[] = [
  {
    name: 'site down',
    description: 'No heartbeat from the public health endpoint — unreachable, process down, or Axiom ingest stopped.',
    apl: `['${METRICS}'] | where metric == 'heartbeat' and environment == 'prod' | summarize count()`,
    operator: 'Below',
    threshold: 1,
    rangeMinutes: 5,
    alertOnNoData: true,
  },
  {
    name: 'health failing',
    description: 'The heartbeat reached the site but it answered not-ok (5xx / unhealthy).',
    apl: `['${METRICS}'] | where metric == 'heartbeat' and environment == 'prod' and ok == false | summarize count()`,
    operator: 'Above',
    threshold: 0,
    rangeMinutes: 5,
  },
  {
    name: 'error logs spike',
    description: 'Surge of error/fatal log lines in production.',
    apl: `['${LOGS}'] | where environment == 'prod' and level in ('error', 'fatal') | summarize count()`,
    operator: 'Above',
    threshold: 10,
    rangeMinutes: 5,
  },
  {
    name: 'http 5xx',
    description: 'Server errors: requests answering with a 5xx status.',
    apl: `['${METRICS}'] | where metric == 'request' and environment == 'prod' and status >= 500 | summarize count()`,
    operator: 'Above',
    threshold: 5,
    rangeMinutes: 5,
  },
  {
    name: 'request latency p95',
    description: 'Request latency p95 over 2s — the site is slow.',
    apl: `['${METRICS}'] | where metric == 'request' and environment == 'prod' | summarize percentile(durationMs, 95)`,
    operator: 'Above',
    threshold: 2000,
    rangeMinutes: 10,
  },
  {
    name: 'worker job failures',
    description: 'Background (pg-boss) jobs are failing.',
    apl: `['${LOGS}'] | where environment == 'prod' and category == 'worker' and level == 'error' | summarize count()`,
    operator: 'Above',
    threshold: 0,
    rangeMinutes: 15,
  },
  {
    name: 'memory rss high',
    description: 'Process RSS is high — a leak or spike. The heartbeat samples memoryUsage() every minute.',
    apl: `['${METRICS}'] | where metric == 'memory' and environment == 'prod' | summarize max(rss)`,
    operator: 'Above',
    // 1 GiB — baseline sits well under this; past it means a leak or spike worth paging on.
    threshold: 1024 * 1024 * 1024,
    rangeMinutes: 5,
  },
]

// Axiom validates a monitor/dashboard APL against the dataset schema at create time, so a field only resolves once an
// event carrying it has been ingested. On a fresh dataset that fails — skip and re-run once data flows, don't abort.
const skip = (kind: string, name: string, error: unknown) =>
  console.warn(
    `[axiom] skipped ${kind} "${name}" — ${error instanceof Error ? error.message : String(error)}. Re-run once the datasets have data.`,
  )

for (const monitor of monitors) {
  try {
    await upsert('monitors', monitor.name, {
      type: 'Threshold',
      description: monitor.description,
      aplQuery: monitor.apl,
      operator: monitor.operator,
      threshold: monitor.threshold,
      intervalMinutes: 1,
      rangeMinutes: monitor.rangeMinutes,
      notifierIds: [notifierId],
      ...(monitor.alertOnNoData ? { alertOnNoData: true } : {}),
    })
  } catch (error) {
    skip('monitor', monitor.name, error)
  }
}

// --- Dashboards --- charts are time-series; the layout flows two per row.
type Chart = { id: string; name: string; apl: string }

const upsertDashboard = async (name: string, charts: Chart[]) => {
  const dashboard = {
    name,
    owner: 'X-AXIOM-EVERYONE',
    schemaVersion: 2,
    refreshTime: 60,
    timeWindowStart: 'qr-now-1d',
    timeWindowEnd: 'qr-now',
    charts: charts.map((chart) => ({ id: chart.id, type: 'TimeSeries', name: chart.name, query: { apl: chart.apl } })),
    layout: charts.map((chart, index) => ({
      i: chart.id,
      x: (index % 2) * 6,
      y: Math.floor(index / 2) * 4,
      w: 6,
      h: 4,
    })),
  }
  try {
    const existing = ((await api('GET', '/dashboards')) ?? []) as Array<{ uid: string; dashboard?: { name?: string } }>
    const found = existing.find((item) => item.dashboard?.name === name)
    if (found) {
      await api('PUT', `/dashboards/uid/${found.uid}`, { dashboard, overwrite: true })
      console.log(`[axiom] updated dashboard "${name}"`)
    } else {
      await api('POST', '/dashboards', { dashboard })
      console.log(`[axiom] created dashboard "${name}"`)
    }
  } catch (error) {
    skip('dashboard', name, error)
  }
}

await upsertDashboard('Overview', [
  {
    id: 'req-rate',
    name: 'Requests',
    apl: `['${METRICS}'] | where metric == 'request' | summarize count() by bin_auto(_time)`,
  },
  {
    id: 'latency',
    name: 'Latency p50 / p95 / p99 (ms)',
    apl: `['${METRICS}'] | where metric == 'request' | summarize p50 = percentile(durationMs, 50), p95 = percentile(durationMs, 95), p99 = percentile(durationMs, 99) by bin_auto(_time)`,
  },
  {
    id: 'status',
    name: 'Responses by status',
    apl: `['${METRICS}'] | where metric == 'request' | summarize count() by bin_auto(_time), status`,
  },
  {
    id: 'errors',
    name: 'Error & fatal logs',
    apl: `['${LOGS}'] | where level in ('error', 'fatal') | summarize count() by bin_auto(_time)`,
  },
  {
    id: 'heartbeat',
    name: 'Heartbeat by target',
    apl: `['${METRICS}'] | where metric == 'heartbeat' | summarize count() by bin_auto(_time), target`,
  },
  {
    id: 'memory',
    name: 'Process memory (bytes)',
    apl: `['${METRICS}'] | where metric == 'memory' | summarize rss = max(rss), heapUsed = max(heapUsed), external = max(external) by bin_auto(_time)`,
  },
])

await upsertDashboard('Auth', [
  {
    id: 'auth-events',
    name: 'Sign-ups & sign-ins',
    apl: `['${LOGS}'] | where category == 'auth' and message in ('Signed in', 'Signed up') | summarize count() by bin_auto(_time), message`,
  },
  {
    id: 'auth-method',
    name: 'By method',
    apl: `['${LOGS}'] | where category == 'auth' and message in ('Signed in', 'Signed up') | summarize count() by bin_auto(_time), props["method"]`,
  },
])

await upsertDashboard('Errors', [
  {
    id: 'err-category',
    name: 'Errors by category',
    apl: `['${LOGS}'] | where level in ('error', 'fatal') | summarize count() by bin_auto(_time), category`,
  },
  {
    id: 'err-name',
    name: 'Top error names',
    apl: `['${LOGS}'] | where level in ('error', 'fatal') | summarize count() by bin_auto(_time), props["error.name"]`,
  },
])

console.log(`[axiom] done — datasets, notifier, ${monitors.length} monitors, 3 dashboards`)
