# AGENTS.md

Operating manual for any coding agent working in this repo. It teaches you how
to find the conventions — it doesn't restate them. They live in JSDoc next to
the code, in `*.md` files, and in `docs/*.md`. Trust them over your priors.

**Running it locally:** [docs/setup.md](docs/setup.md).

**This is the panel of a VibeDPN box**, not a hosted site: one account (the box
admin, password in `secrets/htpasswd`), no sign-up, no mail, no OAuth, and the
core API reached only through `/api/core/*` behind the session. The repository
rules are in `../CLAUDE.md`. Two variants come from one code base — read
the `UI_VARIANT` rule in `src/engine.ts` before adding anything heavy to a screen.

**Working on the boilerplate itself**, not on an app built from it? The
developer manual is [dev/AGENTS.md](dev/AGENTS.md) (branches, releasing,
placeholder rules) — that folder is absent in user copies.

## Mindset

The project already has a helper for most things. Default to **find and reuse**,
not write. Match the surrounding style — if a sibling file does X, do X. "I'll
just inline this" / "I'll write a quick helper" is almost always wrong; search
first.

## Discovery protocol (before any non-trivial task)

1. **Read the rules.** Grep `@tags rule` and read every rule that touches your
   task. Then grep your topic / skim `docs/` and follow `@related` from there.
2. **Find a sibling.** Read the closest existing feature end-to-end; new code
   should be a near-copy, not written from a blank page.
3. **Read JSDocs as you go.** Helpers and bases carry one where it matters;
   `@related` is a navigation graph — follow it. Using a helper without reading
   its JSDoc is guessing. Points (queries, mutations, pages) deliberately have
   none — the chain is the doc.
4. **Search before you create** any helper, schema, error class, field, or UI
   primitive — adding a dependency or hand-rolling one we already have is a
   defect.
5. **Write the smallest change** that fits the existing layout.
6. **Verify** with `bun run check` (types + lint). For UI, run the app and try
   the flow. Add tests for non-trivial logic, following a sibling test.

## Point0 MCP (`mcp__point0-project__*` + `mcp__point0-docs__*`)

Two stdio servers, wired in `.mcp.json`:

- **`mcp__point0-project__*`** — _this project's_ Point0 graph (from
  `src/generated/point0/meta.ts`): roots, bases, plugins, pages, layouts,
  queries, mutations, actions, infiniteQueries, `.lets.*` chains, plugin
  composition, `ctx` vs `with`, prefetching, redirects, OpenAPI exposure.
- **`mcp__point0-docs__*`** — the Point0 framework documentation (concepts and
  syntax), served by `@point0/docs`.

**Consult them before guessing Point0 syntax.** Don't invent examples.

## Docs

- Conventions are docs: `docs/*.md` and JSDoc `@`-directives, found by grepping.
- Read [docs/docs.md](docs/docs.md) before you write or read any doc — it owns
  the format, frontmatter keys, and what to write vs. skip.
- When you change a non-obvious export, update its JSDoc. Stale docs are worse
  than none.
- Asked to pull boilerplate updates (apply a `start0-*..*.diff`)? The flow and
  the rules are in [docs/updating.md](docs/updating.md).

## Writing code

- **Imitate the sibling.** The right shape and naming are in a neighbour file.
- **Don't expand surface area.** No new file kinds, helper bins, or docs
  directories without a reason that belongs in `docs/`.
- **Use the project's helpers** — error class, logger, utilities — found by
  search, not guess. If a pattern looks wrong, raise it; don't bypass it.
- **No defensive code** for cases the types already rule out. **No
  backwards-compat shims** for a path with one caller — delete and rename.
- **Comments only when the _why_ is non-obvious.** No narration of what the code
  does, no references to issues or sessions.

## Commits

Don't commit unless asked. When you do: short imperative subject; the body says
_why_, not _what_. No task numbers, sessions, or self-references.
