---
id: prisma-migrations
tags: rule, prisma, data
---

# Prisma

Do not write migrations manually. Update `src/modules/prisma/schema.prisma`,
then run `bun run prisma:generate` to generate the Prisma client.

To create migrations and regenerate the client, run `bun run prisma:migrate`.

If you need to add types for JSON fields, use `prisma-json-types-generator`.
Prisma JSON types are stored in `./types.ts`.
