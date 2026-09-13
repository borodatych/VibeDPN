---
id: socket
description:
  How sockets are laid out (the channel here, every space and handler next to
  its owner), the naming and addressing rules, and what is wired today.
tags: rule, socket
---

# Sockets

Point0 sockets; full reference: https://1gr14.dev/point0/latest/socket.

This module owns the **channel** — the one connection the whole app rides.
Everything else socket-related lives with whatever owns it, and the rules below
are what keep that from scattering.

## The rules

**Naming.** Everything socket-related lives in a file named `socket.ts(x)` next
to its owner — one glance at a module/feature tells whether it has anything
live:

- the channel itself → `src/modules/socket/channel.ts` (this module, because
  every side of the app connects through it);
- a module's/feature's handlers and spaces → `socket.ts(x)` inside that
  module/feature (`modules/auth/socket.tsx`, `features/idea/socket.ts`) — a
  space belongs where its rooms mean something, not here;
- listener components stay ordinary components (`components/…`), only the points
  go into `socket.*`.

**Addressing.** Pushes ride **rooms** — exact topics: per-user → a
`clientHandler` grown from `userSpace`,
`sendToClient(payload, { room: { userId } })`; per-session (this cookie's tabs
only) → `sessionSpace` the same way; new shapes (chats, live model updates) → a
new space with a `.joiner` (client asks) or `.enroller` (server assigns) in the
owning feature's `socket.ts` — `examples/socket` in the point0 repo has complete
one-file recipes. **Admin commands ride rooms too**: on a space, `refresh` /
`kick` / `kill` / `amendIdentity` take `{ room }` — the same hot indexed address
the pushes use, and with an `.enroller` the room holds exactly the matching live
connections, so there is nothing to scan. `$identity` selections are for
channel-level commands (no room exists there) and one-off selections — scans,
keep them off hot paths.

**Identity.** `{ userId, sessionId }`, captured by the connector at connect
time; it changes only through a reconnect or a server `refresh` (re-runs the
connector and enrollers without dropping sockets) — room-addressed on a space
(`sessionSpace.refresh({ room: { sessionId } })`), by `$identity` on the
channel. If a server-side change affects who a connection is — refresh it.

## What is wired

- `src/modules/socket/channel.ts` — `appChannel`, open to guests: the identity
  is `{ userId, sessionId }`, both `null` when signed out. Held for the whole
  app by one `<appChannel.Connection>` in `app.client.tsx`.
- `src/modules/auth/socket.tsx` — `userSpace` / `sessionSpace` (every signed-in
  connection auto-enrolled into its `{ userId }` and `{ sessionId }` rooms — the
  personal push addresses; guests hold no room) plus what rides them:
  `sessionEndedHandler` (on `sessionSpace`), `userBannedHandler` (on
  `userSpace`), and `AuthSocketSync` (drops signed-in caches on those pushes;
  reconnects when `me` flips INTO a signed-in user). The spaces live there
  because their rooms are auth's own facts, and auth is their only consumer.
- `src/modules/auth/server.ts` — the server side, in better-auth
  `databaseHooks`: every session death (sign-out, revoke, ban, expiry cleanup) →
  push into the session's room + `refresh` of that same room; the ban route →
  push the reason into the user's room + refresh of the user's room + the
  `User Banned` Mixpanel event.
- `src/features/idea/socket.ts` — `ideaCreatedHandler`, the app-wide broadcast
  example (listener: `features/idea/components/created-toast.tsx`).
- `src/lib/backplane.ts` — multi-node delivery over the app's own Postgres
  (`postgresBackplane`, `schema: 'point0'` so `prisma migrate` sees no drift).
  `src/engine.ts` reaches it through a lazy `backplane` factory, so the postgres
  client never loads for a build or for codegen.
