/**
 * Fuzzy score algorithm is a way to measure how similar two strings are
 *
 * @example
 *   fuzzyScore('hello world', 'helloworld') // 94.9
 *   fuzzyScore('hello world', 'hl wrld') // 39.9
 *   fuzzyScore('hello world', 'hod') // 9.9
 *   fuzzyScore('hello world', 'zxcvbnm') // null
 */
export const fuzzyScore = (text: string, query: string): number | null => {
  if (!query) {
    return 0
  }
  const t = text.toLowerCase()
  const q = query.toLowerCase()

  // exact substring match wins big
  const subIdx = t.indexOf(q)
  if (subIdx !== -1) {
    return 1000 - text.length + (subIdx === 0 ? 100 : 0)
  }

  let score = 0
  let ti = 0
  let lastMatch = -2
  let consecutive = 0

  for (let qi = 0; qi < q.length; qi++) {
    const qc = q[qi]
    while (ti < t.length && t[ti] !== qc) {
      ti++
    }
    if (ti >= t.length) {
      return null
    }

    if (ti === lastMatch + 1) {
      consecutive++
      score += 5 + consecutive * 2
    } else {
      consecutive = 0
      score += 1
    }

    if (ti === 0) {
      score += 8
    } else {
      const prev = text[ti - 1]
      const cur = text[ti]
      if (!/[a-z0-9]/i.test(prev)) {
        score += 6
      } else if (prev === prev.toLowerCase() && cur !== cur.toLowerCase()) {
        score += 6
      }
    }

    lastMatch = ti
    ti++
  }

  return score - text.length * 0.1
}
