---
id: updating
tags: update, setup
related: setup
description:
  How to pull boilerplate updates into your app — one CLI command builds the
  diff, your agent applies it.
---

# Updating from Start0

Your app was created from a specific Start0 version and has diverged since —
your code is yours now. So updating is **not a merge**: you look at the diff
between **the two Start0 versions** (the one you started from and the latest)
and apply what's relevant, ideally with an agent doing the legwork.

## One command

```sh
bunx 1gr14@latest update    # run it in the app folder
```

It figures out which version you started from (the `start0` marker in
`package.json` — it ships with the boilerplate, stamped at release), downloads
that version and the latest from [1gr14.dev](https://1gr14.dev), and writes
their diff next to your code:

```
start0-v0.3.0..v0.5.0.diff
```

Already on the latest? It says so and writes nothing. The diff is the
boilerplate against itself — your app's own changes are not in it. The new
`CHANGELOG.md` entries ride along inside the diff, and their **Migration notes**
are the first thing to read.

## Apply it — best with an agent

The command prints this prompt ready to paste:

> My app was created from Start0 v0.3.0. The file start0-v0.3.0..v0.5.0.diff is
> the diff of the boilerplate itself up to v0.5.0 (CHANGELOG.md entries
> included). Go change by change: apply what's relevant to this app, adapt
> renamed pieces to our names, skip what we removed on purpose and list every
> skip with a reason. The diff itself bumps package.json `"start0"` to "v0.5.0"
> — make sure that lands. Finish by deleting the diff file.

Review the result like any PR: the diff is the boilerplate's, the decisions are
yours.

## Pieces, if you want them by hand

- **The marker** — `package.json` → `"start0": { "version": "v0.3.0" }`. It
  comes with the boilerplate, and applying the update diff bumps it. Lost it?
  Add it back, or run `npx 1gr14 update --from <ref>`.
- **A bare snapshot** — `npx 1gr14 download start0 --ref v0.3.0` unpacks any
  version into `start0-v0.3.0/`, handy for reading two versions side by side.
- **Via git instead** — with repo access (the GitHub invitation on
  [1gr14.dev](https://1gr14.dev)), git gives the same diff without downloads:

  ```sh
  git remote add start0 https://github.com/1gr14/start0.git
  git fetch start0 'refs/tags/*:refs/tags/*'
  git diff v0.3.0..v0.5.0
  ```
