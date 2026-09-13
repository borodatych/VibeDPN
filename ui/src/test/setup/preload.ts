import nodePath from 'node:path'

const file = Bun.main
const basename = nodePath.basename(file, nodePath.extname(file))
const parts = basename.split('.')
// const lastPart = parts[parts.length - 1]

// if (lastPart !== 'test') {
//   throw new Error(`Test file basename should end with .test.*, but got "basename" in ${file}`)
// }

type Mode = 'e2e' | 'int' | 'unit' | 'dom'
const mode = parts[parts.length - 2] as Mode | undefined

switch (mode) {
  case 'e2e':
    await import('./e2e')
    break
  case 'int':
    await import('./int')
    break
  case 'dom':
    await import('./dom')
    break
  case 'unit':
  default:
    await import('./unit')
    break
  // default:
  //   throw new Error(`Test file basename should end with .{e2e,int,unit,dom}.test.* but got "${mode}.test.*" in ${file}`)
}
