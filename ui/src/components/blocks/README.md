---
tags: rule, blocks
related: x-dropdown
---

# About project block components

X components are composed, reusable blocks built from `@/components/ui`
primitives — prefixed `X` when they wrap a same-named primitive.

Basic UI primitives live in `@/components/ui`. When we often need to combine and
reuse several primitives together, create a composed component with the
configuration it needs. For example, `XDropdown` exists in
`@/components/blocks/dropdown.tsx` because it combines dropdown primitives into
a reusable block. `InfiniteScroll` in `@/components/blocks/infinite-scroll.tsx`
does not use same-named primitives from `@/components/ui`, so it does not need
the `X` prefix.

- When you need a UI component, prefer an existing `X` component when one
  exists.
- If no ready-made `X` component exists, compose the standard primitives
  locally.
- If the same composition repeats often, create an `X` component for it.
- If an `X` component is missing a small configuration option, add it. If the
  option would make the component much more complex, compose the standard
  primitives locally instead.
