import { z } from 'zod'

/**
 * Reusable Zod primitives, shapes, and prebuilt objects.
 *
 * Use `zz.shape.*` to spread into a larger object schema, `zz.object.*` for the prebuilt schema, and `zz.string.*` for
 * query-string-friendly coercions.
 *
 * @example
 *   z.object({ ...zz.shape.paginationPaged, q: z.string().optional() })
 *   zz.object.sn // { sn: number }
 *
 * @tags zod, schema
 */
// native primitives
const int = z.number().int().positive()

// coerce primitives
const stringNumber = z.coerce.number<number | string>()
const stringDate = z.coerce.date<Date | string>()
const stringInt = stringNumber.int().positive()

// popular schmeas
const id = z.uuid()
const sn = stringInt
const limit = stringInt.min(1).max(100).optional().default(20)
const cursor = stringInt.optional()
const page = stringInt.min(1).optional().default(1)
const password = z.string().min(8)

// shapes of popular object schemas
const shapeId = {
  id,
}
const shapeSn = {
  sn,
}
const shapePaginationPaged = {
  limit,
  page,
}
const shapePaginationCursor = {
  limit,
  cursor,
}

export const zz = {
  int,

  string: {
    number: stringNumber,
    date: stringDate,
    int: stringInt,
  },

  shape: {
    id: shapeId,
    sn: shapeSn,
    paginationPaged: shapePaginationPaged,
    paginationCursor: shapePaginationCursor,
  },

  object: {
    id: z.object(shapeId),
    sn: z.object(shapeSn),
    paginationPaged: z.object(shapePaginationPaged),
    paginationCursor: z.object(shapePaginationCursor),
  },

  id,
  sn,
  limit,
  cursor,
  page,
  password,
}
