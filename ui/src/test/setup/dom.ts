import { GlobalRegistrator } from '@happy-dom/global-registrator'
import { afterEach } from 'bun:test'

if (!GlobalRegistrator.isRegistered) {
  GlobalRegistrator.register()
}

// this module deliberately has **no static import** of
// `@testing-library/*`. Those packages are CommonJS — they capture
// `document.body` at module-load time — and static imports get hoisted ahead
// of any function body, so we must keep them behind a dynamic `import()` that
// fires only *after* `GlobalRegistrator.register()` has run.

const rtl = await import('@testing-library/react')

afterEach(() => {
  rtl.cleanup()
})
