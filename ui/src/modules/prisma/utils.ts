import { Prisma } from '@/generated/prisma/client'

export const isUniqueConflict = (error: unknown, target?: string) => {
  if (!(error instanceof Prisma.PrismaClientKnownRequestError)) {
    return false
  }
  if (error.code !== 'P2002') {
    return false
  }
  if (target) {
    const errorTarget = error.meta?.target
    return Array.isArray(errorTarget) && errorTarget.includes(target)
  }
  return true
}

const queryCommentRegexp = /\s*\/\*((?:[^*]|\*(?!\/))*)\*\/\s*$/
const queryCommentEntryRegexp = /([^=,]+)='((?:\\'|[^'])*)'(?:,|$)/g
const decodeQueryCommentPart = (value: string) => {
  try {
    return decodeURIComponent(value)
  } catch {
    return value
  }
}
const parseQueryComment = (queryComment: string | undefined) => {
  if (!queryComment) {
    return {}
  }

  const tags: Record<string, string> = {}
  const comment = queryComment.slice(2, -2)
  for (const match of comment.matchAll(queryCommentEntryRegexp)) {
    const key = decodeQueryCommentPart(match[1])
    const value = decodeQueryCommentPart(match[2].replaceAll("\\'", "'"))
    tags[key] = value
  }
  return tags
}
export const splitQueryAndComment = (query: string) => {
  const queryCommentMatch = query.match(queryCommentRegexp)
  const queryComment = queryCommentMatch?.[0].trim()
  const queryWithoutComment =
    queryCommentMatch?.index === undefined ? query : query.slice(0, queryCommentMatch.index).trimEnd()
  const queryCommentParsed = parseQueryComment(queryComment)
  return { queryWithoutComment, queryCommentParsed }
}
