---
id: entity-payloads
tags: rule, prisma, data
description: How we define reusable entity selects and payload normalizers
---

# Entity payloads

For each entity shape used by more than one query, declare a `...Select` + a
`normalize...Payload` pair next to each other.

```ts
export const fooSelect = {
  // ...Prisma select
} satisfies Prisma.FooSelect

export type FooPayloadRaw = Prisma.FooGetPayload<{ select: typeof fooSelect }>

export const normalizeFooPayload = (foo: FooPayloadRaw) => {
  // collapse defaults, hide fields, derive booleans, etc.
  return foo
}

export type FooPayload = ReturnType<typeof normalizeFooPayload>
```

Use the names as written — `xxxSelect`, `XxxPayloadRaw`, `normalizeXxxPayload`,
`XxxPayload`. Pick the select first in the loader, then map the rows through the
normalizer before returning:

```ts
const rows = await prisma.foo.findMany({ select: fooSelect })
return { items: rows.map(normalizeFooPayload) }
```

When a view needs a different shape, define another pair (`fooForAdminSelect`,
`normalizeFooForAdminPayload`, ...) instead of conditionally hiding fields in
the consumer.

The normalizer is also the single place to keep an identity passthrough — even
when there is nothing to transform today, having it reserves the seam for later
changes without a downstream rename.
