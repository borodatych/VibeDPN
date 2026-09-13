---
id: axiom
description:
  How Axiom is wired (server-only — a logs sink and event metrics), its env, and
  provisioning the datasets / monitors / dashboards as code.
tags: setup, axiom, logger, metrics
---

# Logs & metrics with Axiom

[Axiom](https://axiom.co) is the server's **log store** and **metrics** backend.
One server-only module — `@/modules/axiom` — opens a single batching client and
exposes:

- **`axiomGetSink()`** — a LogTape sink wired in `lib/logger.ts`, so every
  `logger.*` is mirrored to the logs dataset.
- **`axiomMetric(name, fields)`** — write a metric point from anywhere. A metric
  is just an event (`{ metric, environment, release, ...fields }`) aggregated in
  APL, so adding one is calling this with a new name.
- **`axiomMetricsMiddleware`** — root middleware that meters every request.

`initAxiom()` (in `index.server.ts`) opens the client and registers the shutdown
flush. Off in local, where every entry point no-ops. The heartbeat that feeds
the `site down` monitor lives in `@/modules/health`.

## Why `props` is one map field

A log goes in as
`{ _time, level, category, message, environment, release, props }`, with all log
properties under the single `props` field — not flattened. Axiom caps a dataset
at 256 top-level fields and rejects events past it, and fields are cumulative,
so flattening unbounded log keys would eventually drop logs. `props` is a **map
field**, so its keys don't count toward the cap; query them as
`props["request.id"]`. Metrics stay flat — their fields are author-controlled,
so they stay well under the cap.

## Env

Two server-only vars (required outside local; empty disables Axiom):

- **`AXIOM_TOKEN`** — a basic ingest token scoped to the `logs` / `metrics`
  datasets.
- **`AXIOM_EDGE`** — the region's ingest edge domain (e.g.
  `eu-central-1.aws.edge.axiom.co`); datasets are regional, so ingest must hit
  the edge, not the global control plane.

Dataset names are fixed (`logs` / `metrics`) — the token is org-scoped, so they
never collide.

## Provisioning (advanced token)

`AXIOM_TOKEN_ROOT` is an advanced, org-level token the app never reads — it
lives in `.env.agents`, not `.env`. With it:

- **`bun run axiom:provision`** creates the datasets and `props` map field, the
  email notifier (`ALERT_EMAILS`), the monitors, and the dashboards —
  idempotently. The set lives in `provision.ts`; edit and re-run.
- **Analyze** prod with APL: `POST /v1/datasets/_apl?format=tabular` body
  `{ "apl": "['logs'] | where props[\"request.id\"] == '...'" }`.

Mint the basic `AXIOM_TOKEN` once (Console → API tokens, scoped to `logs` /
`metrics`) for `.env` / Railway.
