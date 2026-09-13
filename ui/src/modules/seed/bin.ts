import { logger } from '@/lib/logger.js'
import { shutdown } from '@/lib/shutdown'
import { seed } from '@/modules/seed/index'

const l = logger.child('seed')

try {
  await seed()
  l.info(`Seeded successfully`)
  process.exitCode = 0
} catch (error) {
  l.error(`Failed to seed`, error)
  process.exitCode = 1
} finally {
  await shutdown(process.exitCode)
}
