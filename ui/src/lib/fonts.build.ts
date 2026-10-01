import { FONTS_ROUTE } from '@/lib/fonts'
import { readFileSync } from 'node:fs'
import path from 'node:path'

/**
 * The faces the panel sets its text in (`--font-*` of styles/index.css), as the Fontsource packages declare them
 *
 * @tags fonts
 * @related panelFonts
 */
export const FONT_STYLESHEETS = [
  '@fontsource-variable/inter/wght.css',
  '@fontsource-variable/fira-code/wght.css',
  '@fontsource/ibm-plex-serif/700.css',
]

const FONT_URL = /url\(\.\/files\/([\w.-]+)\)/g
// the directory of a package, the last segment of its name: `inter`, `fira-code`, `ibm-plex-serif`
const packageDirectory = (specifier: string): string => specifier.split('/')[1]!

/**
 * The stylesheet of the panel fonts and the files it names, read from the Fontsource packages
 *
 * The panel serves both itself: a box asks nothing of a third party, and a slow line to one held every page
 *
 * The files stay files and not `url()` in the bundled CSS: Bun inlines every such asset under 128 KB as a data URL
 * (oven-sh/bun#24599), and the stylesheet would carry all subsets of all faces for every page
 *
 * A package's `files` directory is served whole: the publicdir of Point0 copies directories, not single files
 *
 * A face keeps its `unicode-range`, so a browser fetches only the subsets the page uses
 *
 * @tags fonts
 * @related FONT_STYLESHEETS
 */
export const panelFonts = (from: string): { css: string; directories: Record<string, string> } => {
  const directories: Record<string, string> = {}
  const css = FONT_STYLESHEETS.map((specifier) => {
    const stylesheet = Bun.resolveSync(specifier, from)
    const route = `${FONTS_ROUTE}/${packageDirectory(specifier)}`
    directories[route] = path.join(path.dirname(stylesheet), 'files')
    return readFileSync(stylesheet, 'utf8').replaceAll(FONT_URL, (_match, name: string) => `url(/${route}/${name})`)
  }).join('\n')
  return { css, directories }
}
