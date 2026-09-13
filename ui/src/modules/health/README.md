---
id: health
description:
  The /api/health probe, the network health checks, and the heartbeat worker
  behind Axiom's liveness alert.
tags: setup, health, infra
---

# Health & heartbeat

`/api/health` is the liveness probe Railway hits. It also returns the live
deploy as the `x-release` header, so an external check can read which release is
serving.

`isApiHealthyDetailed` / `isClientHealthyDetailed` fetch the API and the client
over the network and report `{ ok, status, durationMs }`. The boolean
`isApiHealthy` / `isClientHealthy` and the `waitFor*` helpers (used by the e2e
setup to wait for a booting server) build on them.

`heartbeatWorker` runs both once a minute and writes a `heartbeat` metric per
target to Axiom. The check goes over the real public URL, so it measures
end-to-end reachability — DNS, TLS, the Railway edge, the app — not in-process
state. When the beat stops, Axiom's `site down` monitor fires: the **absence**
of the metric is the alert. Off in local (no public URL, Axiom disabled).
