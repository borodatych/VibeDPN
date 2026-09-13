---
id: docker
tags: docker, setup
description: How the panel image is built and started on a box
related: setup
---

# Docker

The panel ships as `ghcr.io/borodatych/vibedpn-ui` and runs from the repository
`compose.yaml` (profile `ui`) next to its own Postgres `ui-db`. Nothing is built
on the box: `dist/` needs about 2 GiB of memory to build, so CI builds the image.

## Image

- The build stage runs on the build platform and produces `dist/` once; only the
  runtime stage is per architecture (amd64, arm64).
- `docker-entrypoint.sh` refuses to start without `HTPASSWD_FILE`,
  `/run/secrets/ui-db-password` or `/run/secrets/ui-auth-secret`, assembles
  `DATABASE_URL` and `BETTER_AUTH_SECRET` from them, then applies migrations and
  starts the server.

## Run on a box

`vibedpn init` generates the secrets and `vibedpn up` starts `ui-db` and `ui`.
The panel listens on `VIBEDPN_LAN_IP:VIBEDPN_UI_PORT`; `ui-db` publishes Postgres
on `127.0.0.1:VIBEDPN_UI_DB_PORT` only.

## Just the DB for development

```sh
docker run -d --name vibedpn-ui-db -e POSTGRES_USER=vibedpn -e POSTGRES_PASSWORD=vibedpn \
  -e POSTGRES_DB=vibedpn -p 127.0.0.1:5432:5432 postgres:17-alpine
```
