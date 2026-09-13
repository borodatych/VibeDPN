import { killPort } from '@point0/engine/port'
import { afterAll, setDefaultTimeout } from 'bun:test'
import nodePath from 'node:path'

setDefaultTimeout(20000)

// how to build project
const buildCommand = ['bun', 'run', 'build:code']

// how to run in dev mode without building (option 1, default)
const runDevCommand = ['bun', 'point0', 'dev']

// how to run main server process after building (option 2, when process.env.E2E_TESTS_BUILD === 'true')
const indexServerFile = nodePath.resolve(__dirname, '..', '..', '..', 'dist', 'server', 'index.server.js')
const runBuiltCommand = ['bun', 'run', indexServerFile]

// (option 3, if you run by yourself "bun run dev:test", then you can run tests with process.env.E2E_TESTS_NO_RUN === 'true', and have faster start time)

// eslint-disable-next-line no-restricted-properties -- test-runner flag, set by the `test:e2e:*` scripts; in no app shape
const shouldBuild = process.env.E2E_TESTS_BUILD === 'true'
if (shouldBuild) {
  // eslint-disable-next-line no-restricted-properties -- test setup: it SETS the variable, before preload resolves env
  process.env.CLIENT_URL = process.env.SERVER_URL
}

// eslint-disable-next-line no-restricted-properties -- test-runner flag, set by the `test:e2e:*` scripts; in no app shape
const shouldRun = process.env.E2E_TESTS_NO_RUN !== 'true'
if (shouldRun) {
  // eslint-disable-next-line no-restricted-properties -- runs before preload resolves env, so the handles are not up yet
  await killPort([Number(process.env.CLIENT_PORT!), Number(process.env.SERVER_PORT)])
}

await import('@/preload')

const runCommand = async (command: string[]) => {
  const subprocess = Bun.spawn(command, {
    stdout: 'inherit',
    stderr: 'inherit',
    env: {
      // eslint-disable-next-line no-restricted-properties -- the child inherits the whole raw environment, not a shape
      ...process.env,
      NODE_ENV: 'test',
    },
  })

  const exitCode = await subprocess.exited

  if (exitCode !== 0) {
    throw new Error(`Command failed with exit code ${exitCode}: ${command.join(' ')}`)
  }
}

if (shouldBuild && shouldRun) {
  await runCommand(buildCommand)
}

const mainProcess = !shouldRun
  ? undefined
  : shouldBuild
    ? Bun.spawn(runBuiltCommand, {
        stdout: 'inherit',
        stderr: 'inherit',
        env: {
          // eslint-disable-next-line no-restricted-properties -- the child inherits the whole raw environment, not a shape
          ...process.env,
          NODE_ENV: 'test',
        },
      })
    : Bun.spawn(runDevCommand, {
        stdout: 'inherit',
        stderr: 'inherit',
        env: {
          // eslint-disable-next-line no-restricted-properties -- the child inherits the whole raw environment, not a shape
          ...process.env,
          NODE_ENV: 'test',
        },
      })

const killMainProcess = () => {
  if (!mainProcess?.killed) {
    mainProcess?.kill()
  }
}

afterAll(() => {
  killMainProcess()
})

// signal-exit doesn't hold the process for cleanup under Bun, so use plain listeners: kill the spawned app process if
// THIS test process exits — on a normal exit or a termination signal — so an interrupted e2e run never orphans it.
process.on('exit', killMainProcess)
for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP'] as const) {
  process.once(signal, () => {
    killMainProcess()
    process.exit(1)
  })
}

const { waitForApiToBeHealthy, waitForClientToBeHealthy } = await import('@/modules/health/utils')

try {
  await Promise.race([
    (async () => {
      if (!shouldRun) {
        return await new Promise(() => {})
      }
      const exitCode = await mainProcess?.exited
      throw new Error(`Main process exited before becoming healthy with exit code ${exitCode}`)
    })(),
    (async () => {
      await waitForApiToBeHealthy()
      await waitForClientToBeHealthy()
    })(),
  ])
} catch (error) {
  killMainProcess()
  throw error
}
