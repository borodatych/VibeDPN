---
id: docs
description:
  When something is a doc, where it lives, and the keys (tags, related, id) we
  use.
tags: rule, docs
---

# How we write docs

Our docs are the docs we already write — JSDoc next to the code and Markdown
files — kept **in place**, where the developer sees them and an agent finds them
by reading the code or grepping. There's no index to maintain: grep `@tags rule`
and skim `docs/` for the rules, then follow `@related` from there.

> A docs indexer will later parse all of this — the `docs/*.md` files and the
> JSDoc `@`-directives across `src/` — into one searchable collection (CLI / MCP
> / web). It isn't wired up yet. We already author to its conventions below, so
> the day it lands everything just works — and the discipline pays for itself in
> the meantime.

## Keep it simple

Docs here are short and plain. Write like you'd explain it to a colleague:
simple words, easy to read, no cleverness, no clutter. **Where there's nothing
worth saying — or it shouldn't draw attention — write no doc at all.** A good
name and clear types already document themselves; don't narrate what the code
obviously does. Everything should feel natural, not bolted on.

The test for every sentence: **what would a reader do wrong without it?** No
answer — cut the sentence. A doc earns its place by preventing a mistake or a
wrong turn, not by describing.

**Points are self-documenting.** A query, mutation, action, page, or layout
reads as its own spec — the name, the input schema, the plugins in its chain,
and the loader body say everything a doc would. Don't JSDoc them. The rare
exception is a non-obvious contract the chain can't show (`getMeQuery`'s
never-stale caching) — then document the contract, not the point. The same
default applies to per-point input schemas, shadcn `ui/` primitives, and tests.

**Avoid tables.** They're a pain to hand-write and to read in the raw Markdown
source. Put the content in short bullets or a few subheadings instead — reach
for a table only when the data is genuinely a two-dimensional grid you'd scan
both ways.

## When is something a doc

There is no `docs: true` marker. A comment becomes a doc the moment it carries a
key — a JSDoc line like `@tags ...` (or `@id` / `@related`, or a bare `@doc`).
No key → it's a normal comment: still shown on hover, just not a findable doc.
Markdown joins by living under a docs path; opt a file out with `doc: false` in
its frontmatter.

So **adding `@tags` is the act of saying "this is a doc."** Add it when someone
who **isn't looking at this code** would need to find it:

1. It's a **rule** — a decision you must follow. → `@tags rule`
2. It's the **canonical home** of a concept or helper others should reuse
   instead of reinventing.
3. It's an **entry point** — the module or base you'd land on exploring an area.

Leave it a plain comment (no key) when the name + types already say it, when it
only helps whoever is editing that exact line (impl notes, caveats, TODOs), or
when it would repeat another doc — use `@related` there instead.

## Where a doc lives — by scope

1. **JSDoc next to the code** — the default. Travels with the symbol; visible on
   hover. Keep it slim: the _why_, the gotchas, nothing more.
2. **`README.md` (or a `docs/` folder) inside a module/feature** — for what no
   single file can say: the one-or-two-sentence purpose, the non-obvious
   decisions and their why, the cross-module seams. **Never a file inventory** —
   "`api.ts` — the queries, `pages/` — the pages" restates what `ls` and
   [structure](./structure.md) already say, and rots on the first refactor.
3. **`docs/*.md` at the repo root** — only when it applies across _multiple_
   modules (project-wide rules, vocabulary, infra). These get an `id:` so any
   JSDoc can `@related` them.

Don't promote a doc up the hierarchy until its scope demands it.

## The keys

Keep them minimal: usually just `@tags`, plus `@related` when there's somewhere
to point. In JSDoc a key is `@name` with no colon; in Markdown it's a
frontmatter key. There's no required `title` or `description` — the heading and
the prose are enough; just write a normal description.

```ts
/**
 * Money is stored in minor units (cents). Format only through here — never do
 * currency math in the UI.
 *
 * @tags rule, money, payments
 * @related cartTotal
 */
export const formatMoney = (minor: number): string =>
  `$${(minor / 100).toFixed(2)}`
```

### `tags` — the facets

What the doc is, for grepping (and, later, `list --tag`):

- **`rule`** — the one that matters: this doc is **binding**, you must follow
  it.
- **kind**: `plugin`, `util`, `component`, `field`, `schema`, `webhook`,
  `setup`, ... A kind like `query` exists only for the rare documented point — a
  kind tag is never a reason to document every instance of that kind.
- **tech**: `zod`, `pg-boss`, `better-auth`, `dodopayments`, `prisma`, `point0`,
  ...
- **area** (optional): the part of the app it belongs to — `auth`, `payments`,
  `subscription`, `form`, `worker`, `github`, `data`, `i18n`, `email`, `infra`,
  ... Add one as a plain tag when it helps; skip it for a cross-cutting helper.

### `rule` — binding docs

A **rule** is guidance an agent or developer must obey, not just informative
("money in minor units", "don't hand-write migrations", "`@/*` is the only
alias"). Mark it `@tags rule` and `@related` the code it governs. This is what
makes a grep for `@tags rule` — the first thing to do on a task — useful.

Library and tool preferences are rules too — "use `ms` for durations", "throw
`AppError`, not `Error`". An agent can't infer them and will hand-roll or pull
in a competing dependency; write them down.

### `id` — the stable name

Defaults: in JSDoc, the symbol name (or file/dir name if not on a symbol); in
Markdown, the file name (or dir name for `README.md`). Set `@id` only to
override — and you **must** override when ids would collide: a module's
`index.ts` export and its `README.md` both default to the folder name, so give
the export an explicit id (e.g. `@id prisma-service`). Two docs with the same id
clash silently — one wins and links turn ambiguous.

### `related` — links by id, not path

`@related <id>` — the symbol name or a doc's `id`. A trailing `!` marks
must-read: `@related setup!`. Use ids, never file paths: paths rot on refactor,
ids survive. Link only to symbols that are themselves docs — `@related` to an
undocumented symbol silently does nothing.

**Direction.** Link toward what a reader reaches for next: caller → callee, an
instance → the pattern it follows, a part → its assembly index. Two-way only for
genuine pairs or peers (a factory ↔ its index, sibling plugins).

**One canonical doc per repeated pattern.** When the same pattern recurs across
several symbols (e.g. provider webhooks across handlers), document it once on a
canonical rule/example and `@related` it from each instance — don't restate it
everywhere.

**Factory + assembly index.** When a module grows a factory plus an `index.ts`
where everything is registered, the index becomes a `rule` doc with an explicit
`@id <module>-index` stating the runtime essence (what assembles here,
start/stop order) — the factory and each registered item `@related` it. Don't
restate any item's internals there.

## Writing well

- **Lead with the why, not the what.** The reader sees params and types already.
  Explain side effects, ordering, invariants, when to reach for it vs. an
  alternative.
- **Never duplicate.** Don't restate a signature, a Prisma select, or another
  doc. If two symbols share an explanation, write it once in `docs/<id>.md` and
  `@related` it from both.
- **`@example` is for our symbol**, not the underlying framework. No
  `bun add`-level or `@point0/core` tutorials.
- **Format `@example` without code fences** — it's content already; indent two
  spaces:

```ts
/**
 * @example
 *   formatMoney(1234) // "$12.34"
 */
```
