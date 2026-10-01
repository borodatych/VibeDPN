/**
 * Where the panel serves its font files and their stylesheet (lib/fonts.build.ts builds both)
 *
 * Apart from the build module, so that App linking the stylesheet does not pull file reading into the browser bundle
 *
 * @tags fonts
 * @related panelFonts
 */
export const FONTS_ROUTE = 'fonts'
export const FONTS_STYLESHEET = `${FONTS_ROUTE}.css`
