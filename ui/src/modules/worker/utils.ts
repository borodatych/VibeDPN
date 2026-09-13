import { AppError } from '@/lib/error'
import { logger } from '@/lib/logger'
import { onShutdown } from '@/lib/shutdown'
import { omit } from '@/utils/pick'
import { serverEnv } from '@/modules/env/server'
import { prisma } from '@/modules/prisma'
import { env } from '@point0/core'
import memoize from 'memoizee'
import type {
  ConstructorOptions,
  Job,
  Queue,
  QueueOptions,
  QueuePolicy,
  ScheduleOptions,
  SendOptions,
  WorkHandler,
  WorkOptions,
} from 'pg-boss'
import { fromPrisma, PgBoss } from 'pg-boss'

const l = logger.child('worker')

/**
 * The pg-boss queue singleton. Connects lazily: `startBoss` (called from each worker's `ensureQueue`) starts it on
 * first use and registers its shutdown — nothing starts it up front. Workers enqueue inside a Prisma transaction.
 *
 * @tags worker, pg-boss
 * @related createWorker, prisma
 */
export const pgboss = new PgBoss({
  connectionString: serverEnv.DATABASE_URL,
  // `__test__enableSpies` is an internal pg-boss option (still honored at runtime) its public ConstructorOptions type no
  // longer lists — pass it via a cast. It enables `getSpy`, used by the test-only job waiters below.
  __test__enableSpies: env.mode.is.test,
} as ConstructorOptions)

pgboss.on('error', (error) => {
  l.error(error)
})

// Start pg-boss exactly once, on first worker use. Memoized so concurrent `ensureQueue` calls share a single start.
const startBoss = memoize(
  async () => {
    onShutdown('pgboss', ['prisma'], async () => await pgboss.stop())
    await pgboss.start()
  },
  {
    promise: true,
  },
)

/**
 * Common cron expressions for `createWorker({ schedule: { cron } })`.
 *
 * @tags worker, cron
 */
export const every = {
  minute: `*/1 * * * *`,
  hour: `0 * * * *`,
  day: `0 0 * * *`,
  week: `0 0 * * 0`,
  month: `0 0 1 * *`,
  year: `0 0 1 1 *`,
}

type CustomScheduleOptions<TData extends object | void | undefined> = ScheduleOptions &
  (TData extends void ? { cron: string; data?: null | undefined } : { cron: string; data: NoInfer<TData> })

type CustomQueueOptions<TData extends object | void | undefined> = Omit<Queue, 'name'> &
  QueueOptions & {
    /**
     * The queue policy dictates how jobs are allowed to be queued and processed.
     *
     * - `standard` supports all standard features such as deferral, priority, and throttling.
     * - `short` only allows 1 job to be queued, unlimited active. Can be extended with `singletonKey`.
     * - `singleton` only allows 1 job to be active, unlimited queued. Can be extended with `singletonKey`.
     * - `stately` offers a combination of `short` and `singleton`; only allows 1 job per state, queued and/or active. Can
     *   be extended with `singletonKey`.
     * - `exclusive` only allows 1 job to be queued or active. Can be extended with singletonKey`.
     * - `key_strict_fifo` ensures strict FIFO ordering per `singletonKey`. Requires `singletonKey` on every job. Blocks
     *   processing of jobs with the same key while any job with that key is active, in retry, or failed.
     */
    policy?: QueuePolicy
    singletonKey?: TData extends void ? never : (data: NoInfer<TData>) => string
  }

type CustomWorkOptions = WorkOptions

/**
 * Create the queue, and reconcile its `policy` with the code when they've drifted apart.
 *
 * A queue keeps the policy it was CREATED with: `create_queue` is `INSERT ... ON CONFLICT DO NOTHING`, and pg-boss
 * rejects `updateQueue({ policy })` outright — the policy is enforced by partial unique indexes on the job table, so it
 * can't be altered under live jobs. Without this, editing `policy` in a `createWorker` call would silently do nothing
 * on every database that already ran, and you'd think the change had landed.
 *
 * Recreating the queue is the only way to apply it, so that's what we do — but only when the queue is EMPTY. Dropping
 * cascades the cron schedule away too (`schedule.name REFERENCES queue ON DELETE CASCADE`), and `start()` re-schedules
 * right after, so it all settles on the next boot. If real work is queued or running we refuse and warn instead: an
 * unapplied policy is annoying, silently deleting someone's jobs is not.
 */
const createQueue = memoize(
  async (name: string, queueOptions: CustomQueueOptions<any> | undefined) => {
    const options = queueOptions && omit(queueOptions, ['singletonKey'])
    await pgboss.createQueue(name, options)

    const wanted = queueOptions?.policy
    if (!wanted) {
      return
    }
    const existing = await pgboss.getQueue(name)
    if (!existing || existing.policy === wanted) {
      return // the overwhelmingly common path: one extra read per queue per process
    }

    // Count unfinished jobs from the JOB TABLE, never from `QueueResult`'s counts — `queuedCount`/`activeCount` are
    // denormalized columns on the queue row that pg-boss's monitor refreshes on an interval, so they read 0 while real
    // jobs sit in the queue. Trusting them here would delete live work. `findJobs` hits the table itself; `queued: true`
    // would exclude `active`, so filter by state instead. This only runs while a policy mismatch exists, so the full
    // scan is a one-off, not a per-boot cost.
    const unfinished = (await pgboss.findJobs(name)).filter(
      (job) => job.state === 'created' || job.state === 'retry' || job.state === 'active',
    )
    if (unfinished.length > 0) {
      l.warn('Queue policy differs from the code, but the queue has unfinished jobs — keeping the existing policy', {
        queue: name,
        code: wanted,
        database: existing.policy,
        unfinished: unfinished.length,
        fix: 'the new policy is applied on the first boot that finds the queue drained',
      })
      return
    }

    await pgboss.deleteQueue(name)
    await pgboss.createQueue(name, options)
    // `deleteQueue` swallows its own errors, so confirm the recreate took rather than assume it.
    const recreated = await pgboss.getQueue(name)
    if (recreated?.policy === wanted) {
      l.info('Queue recreated to apply a changed policy', { queue: name, from: existing.policy, to: wanted })
    } else {
      l.warn('Failed to apply the changed queue policy', { queue: name, code: wanted, database: recreated?.policy })
    }
  },
  {
    promise: true,
    normalizer: ([name]) => name,
  },
)

const wrapHandlerWithLogger = <T extends (...args: any[]) => any>({
  handler,
  queue,
  jobs,
}: {
  handler: T
  queue: string
  jobs: Job<any>[]
}): T => {
  return (async (...args) => {
    try {
      const output = await handler(...args)
      l.info(`Job completed`, { queue, jobs: jobs.map((job) => job.id), output })
      return output
    } catch (error) {
      l.error(`Job failed`, { error, queue, jobs: jobs.map((job) => job.id) })
      throw error
    }
  }) as T
}

const createWorkerHelpers = <TData extends object | void | undefined, TOutput>({
  name,
  ensureQueue,
  work,
  queueOptionsGeneral,
  workOptionsGeneral,
  scheduleOptionsGeneral,
}: {
  name: string
  ensureQueue: () => Promise<void>
  work: (options?: CustomWorkOptions) => Promise<string>
  queueOptionsGeneral: CustomQueueOptions<TData> | undefined
  workOptionsGeneral: (CustomWorkOptions & { enabled?: boolean }) | undefined
  scheduleOptionsGeneral:
    (Omit<CustomScheduleOptions<TData>, 'cron'> & { enabled?: boolean; cron: string | null }) | undefined
}) => {
  const send = async (data: TData, options?: SendOptions) => {
    await ensureQueue()
    const singletonKey =
      options && 'singletonKey' in options
        ? options.singletonKey
        : queueOptionsGeneral && typeof queueOptionsGeneral.singletonKey === 'function'
          ? queueOptionsGeneral.singletonKey(data as never)
          : undefined
    const jobId = await prisma.$transaction(async (tx) => {
      return await pgboss.send(name, data ?? null, { db: fromPrisma(tx), ...options, singletonKey })
    })
    return jobId
  }
  const schedule = async (cron: string, data: TData, options?: ScheduleOptions) => {
    await ensureQueue()
    return await pgboss.schedule(name, cron, data ?? null, options)
  }
  const unschedule = async () => {
    await ensureQueue()
    return await pgboss.unschedule(name)
  }
  const start = async () => {
    await ensureQueue()
    const { enabled: workEnabled, ...restWorkOptions } = workOptionsGeneral ?? {}
    if (workEnabled !== false) {
      await work(restWorkOptions)
    }
    if (scheduleOptionsGeneral) {
      const { cron, data, enabled: scheduleEnabled, ...restScheduleOptions } = scheduleOptionsGeneral
      if (cron === null) {
        await unschedule()
        return
      }
      if (scheduleEnabled === false) {
        // Skip creating, never delete: the schedule is global state shared by every machine on this database —
        // `cron: null` is the explicit way to remove one. Execution is gated separately, by `work.enabled`.
        return
      }
      await schedule(cron, data as never, restScheduleOptions)
    }
  }
  const Infer = null as never as {
    Data: TData
    Output: TOutput
  }
  return {
    Infer,
    name,
    start,
    send,
    schedule,
    unschedule,
  }
}

/**
 * Define a background worker — never enqueue on raw pg-boss directly; this wrapper adds retries, dedupe,
 * transaction-scoped enqueue, and off-request execution. When to reach for a worker and the naming / registration
 * conventions live in the module README (`worker`).
 *
 * `send(data)` joins a surrounding Prisma transaction and only enqueues on commit. Combine `queue.singletonKey: (data)
 * => string` with a non-`standard` `queue.policy` to dedupe per logical id. `schedule.cron: null` unschedules on next
 * boot.
 *
 * @example
 *   export const syncFooWorker = createWorker(
 *     'syncFoo',
 *     async ({ id }: { id: string }) => { ... },
 *     {
 *       queue: { policy: 'singleton', singletonKey: ({ id }) => id, retryLimit: 3, retryDelay: 60 },
 *       schedule: { cron: every.hour },
 *     },
 *   )
 *
 * @tags worker, pg-boss
 * @related worker, worker-index, createBatchWorker, every, waitForJob
 */
export function createWorker<TData extends object | void | undefined = void, TOutput = void>(
  name: string,
  handler: (data: TData) => Promise<TOutput>,
  options?: {
    queue?: CustomQueueOptions<TData>
    work?: CustomWorkOptions & { batchSize?: 1; enabled?: boolean }
    schedule?: Omit<CustomScheduleOptions<TData>, 'cron'> & { enabled?: boolean; cron: string | null }
  },
) {
  const { queue: queueOptionsGeneral, work: workOptionsGeneral, schedule: scheduleOptionsGeneral } = options ?? {}
  const ensureQueue = async () => {
    await startBoss()
    await createQueue(name, queueOptionsGeneral)
  }
  const work = async (workOptions: Exclude<CustomWorkOptions, 'batchSize'> = {}) => {
    await ensureQueue()
    return await pgboss.work<TData, TOutput>(
      name,
      workOptions,
      async ([job]) => await wrapHandlerWithLogger({ handler, queue: name, jobs: [job] })(job.data),
    )
  }
  const helpers = createWorkerHelpers<TData, TOutput>({
    name,
    ensureQueue,
    work,
    queueOptionsGeneral,
    workOptionsGeneral,
    scheduleOptionsGeneral,
  })
  return {
    ...helpers,
    work,
  }
}

/**
 * Same as `createWorker` but the handler receives the full `jobs` array instead of a single `data` payload. Use when
 * the work can be batched.
 *
 * @tags worker, pg-boss
 * @related createWorker
 */
export function createBatchWorker<TData extends object | void | undefined = void, TOutput = void>(
  name: string,
  handler: WorkHandler<TData, TOutput>,
  options?: {
    queue?: CustomQueueOptions<TData>
    work?: CustomWorkOptions & { enabled?: boolean }
    schedule?: Omit<CustomScheduleOptions<TData>, 'cron'> & { enabled?: boolean; cron: string | null }
  },
) {
  const { queue: queueOptionsGeneral, work: workOptionsGeneral, schedule: scheduleOptionsGeneral } = options ?? {}
  const ensureQueue = async () => {
    await startBoss()
    await createQueue(name, queueOptionsGeneral)
  }
  const work = async (workOptions: CustomWorkOptions = {}) => {
    await ensureQueue()
    return await pgboss.work<TData, TOutput>(
      name,
      workOptions,
      async (jobs) => await wrapHandlerWithLogger({ handler, queue: name, jobs })(jobs),
    )
  }
  const helpers = createWorkerHelpers<TData, TOutput>({
    name,
    ensureQueue,
    work,
    queueOptionsGeneral,
    workOptionsGeneral,
    scheduleOptionsGeneral,
  })
  return {
    ...helpers,
    work,
  }
}

// test utils

const TEST_JOB_TIMEOUT_MS = 3000
const TEST_ALL_JOBS_TIMEOUT_MS = 5000

const withTimeout = async <T>(promise: Promise<T>, ms: number, error: AppError) => {
  let timeout: ReturnType<typeof setTimeout> | undefined
  try {
    return await Promise.race([
      promise,
      new Promise<never>((_, reject) => {
        timeout = setTimeout(() => {
          reject(error)
        }, ms)
      }),
    ])
  } finally {
    if (timeout) {
      clearTimeout(timeout)
    }
  }
}

/**
 * Block until a queued job either completes or fails. Test-only.
 *
 * @tags worker, test
 */
export const waitForJob = async (job: Pick<Job, 'id' | 'name'>) => {
  if (!env.mode.is.test) {
    throw new Error('waitForJob is supported in test mode only')
  }
  // Spies are per-queue in pg-boss — get the one for this job's queue (`job.name`), then await the specific id.
  const spy = pgboss.getSpy(job.name)
  const resolvedJob = await withTimeout(
    Promise.race([spy.waitForJobWithId(job.id, 'completed'), spy.waitForJobWithId(job.id, 'failed')]),
    TEST_JOB_TIMEOUT_MS,
    new AppError('Job timed out', { meta: job }),
  )
  if (resolvedJob.state == 'failed') {
    throw new AppError(`Job failed`, {
      meta: { ...resolvedJob },
    })
  }
}

const waitForAllJobsOnce = async () => {
  if (!env.mode.is.test) {
    throw new Error('waitForAllJobs is supported in test mode only')
  }
  let wasPendingJobs = false
  const queues = await pgboss.getQueues()
  for (const queue of queues) {
    const jobs = await pgboss.findJobs(queue.name)
    for (const job of jobs) {
      wasPendingJobs = true
      await waitForJob(job)
    }
  }
  return { wasPendingJobs }
}

const waitForAllJobsUntilNoPending = async () => {
  for (;;) {
    const { wasPendingJobs } = await waitForAllJobsOnce()
    if (!wasPendingJobs) {
      break
    }
  }
}

/**
 * Block until every queue is drained. Test-only.
 *
 * @tags worker, test
 */
export const waitForAllJobs = async () => {
  if (!env.mode.is.test) {
    throw new Error('waitForAllJobs is supported in test mode only')
  }
  await withTimeout(
    waitForAllJobsUntilNoPending(),
    TEST_ALL_JOBS_TIMEOUT_MS,
    new AppError('Timed out waiting for all jobs'),
  )
}
