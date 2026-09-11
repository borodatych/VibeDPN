# Техническая спецификация

Живой документ: стек, версии, образы, сервисы и раскладка на коробке. Замысел и архитектура — в
[idea.md](idea.md) (не правится), решения по стадиям — здесь. Версии проверены по официальным
источникам 2026-09-11, ссылки — в [knowledge/](knowledge/README.md).

## Хост

| | |
|---|---|
| ОС | Debian 12 (bookworm, ядро 6.1) / Debian 13 (trixie, ядро 6.12) / Raspberry Pi OS 64-bit (trixie) |
| Архитектуры | amd64, arm64 (Raspberry Pi 4/5, N100, любой Debian-хост или VPS) |
| Требования | Docker Engine + Compose v2 (проверено на 5.5.1), модули ядра `wireguard` и `nf_tables` (в стоковых ядрах есть) |
| Каталог | `/opt/vibedpn` — клон репозитория; рядом `config.yaml`, `.env`, `secrets/`, `data/` |

## Стек

| Слой | Технологии | Версии |
|---|---|---|
| `core/` | Python, FastAPI, Pydantic v2, Typer, httpx, Jinja2, ruamel.yaml (YAML 1.2), uvicorn | Python 3.12.14 (security-only до 2028-10), fastapi 0.141, pydantic 2.13, typer 0.27, uvicorn 0.52 — точные версии в `core/uv.lock` |
| Тулчейн core | uv, ruff, mypy strict + плагин pydantic, pytest | uv 0.12.13, ruff 0.16.7, mypy 2.3.1, pytest 9.1.1 |
| `images/wg/` | Alpine + `wireguard-tools-wg` + `iproute2` + `nftables` | alpine 3.24 |
| `ui/` | React + TypeScript strict + Vite + Tailwind + shadcn/ui + Zustand, отдаёт nginx | react 19.3, vite 8.3, TypeScript **6.0.x** (typescript-eslint не поддерживает 7), tailwind 4.3, node 24 (Active LTS) — Stage 6 |
| CI | GitHub Actions: ruff, mypy, pytest, shellcheck, actionlint, `compose config`, buildx multi-arch → GHCR | checkout v7, setup-uv v10.1.0, setup-node v7, docker/* v4/v6/v7 |

## Образы

| Образ | Откуда | Тег |
|---|---|---|
| `ghcr.io/vibebrainsprojects/vibedpn-core` | `core/Dockerfile`, `python:3.12-slim-trixie`, зависимости из `uv.lock` | `${VIBEDPN_TAG}` (`latest` = main, `next`, `sha-…`, semver из тегов `v*`) |
| `ghcr.io/vibebrainsprojects/vibedpn-wg` | `images/wg/Dockerfile`, `alpine:3.24` | `${VIBEDPN_TAG}` |
| `ghcr.io/vibebrainsprojects/vibedpn-ui` | `ui/Dockerfile`, `nginx:1.31-alpine` (mainline) | `${VIBEDPN_TAG}` |
| `mysteriumnetwork/myst` | Docker Hub, multi-arch amd64/arm64/arm-v7 | `1.39.5-alpine` (`${MYST_TAG}`) |
| `adguard/adguardhome` | Docker Hub, multi-arch | `v0.107.79` (`${ADGUARD_TAG}`) |

## Сервисы `compose.yaml`

| Сервис | Профиль | Сеть | Порты и особенности |
|---|---|---|---|
| `core` | всегда | host, `NET_ADMIN` | API на `127.0.0.1:${VIBEDPN_API_PORT}` (4480); монтирует `config.yaml` (ro), `secrets/`, `data/core`; healthcheck `GET /health` |
| `ui` | `ui` | host | nginx на `${VIBEDPN_LAN_IP}:${VIBEDPN_UI_PORT}` (80), `/api/` → core; зависит от здорового `core` |
| `myst-provider` | `provider` | bridge | `127.0.0.1:4449` NodeUI, `127.0.0.1:4050` TequilAPI, UDP `${VIBEDPN_MYST_UDP_FROM}-${VIBEDPN_MYST_UDP_TO}` (56000-56100); `myst --udp.ports=… --traversal=… --tequilapi.* service --agreed-terms-and-conditions` (глобальные флаги — до команды); том `data/myst-provider` |
| `myst-consumer` | `consumer` | `vibedpn-upstreams` 10.77.0.20, `NET_ADMIN`, `ip_forward=1` | `myst --firewall.killSwitch.always --ui.enable=false --tequilapi.* daemon`; том `data/myst-consumer` |
| `wg-client` | `wg-client` | `vibedpn-upstreams` 10.77.0.10, `NET_ADMIN`, `ip_forward=1`, `src_valid_mark=1` | `secrets/wg-client.conf` → `/etc/wireguard/wg0.conf`; entrypoint `client` (Stage 3) |
| `wg-server` | `wg-server` | host, `NET_ADMIN` | `secrets/wg-server/` → `/etc/wireguard`; UDP 51820 открывает nft-baseline core; entrypoint `server` (Stage 3) |
| `adguard` | `dns` | host | тома `data/adguard/{work,conf}`; `AdGuardHome.yaml` рендерит core (Stage 4), веб-панель на `${VIBEDPN_LAN_IP}:3000` |

Сеть `vibedpn-upstreams` — `10.77.0.0/24`, bridge со статическими адресами шлюзов и опцией
`trusted_host_interfaces=${VIBEDPN_LAN_IFACE}`: без неё Docker Engine ≥ 28 не пропускает трафик
LAN к IP контейнеров ([knowledge/docker/directRouting.md](knowledge/docker/directRouting.md)).

## Файлы на коробке

| Путь | Что | В бэкап |
|---|---|---|
| `config.yaml` | единственный источник правды ([manuals/configSpec.md](manuals/configSpec.md)) | да |
| `.env` | производные для compose + `VIBEDPN_TAG`; пишет `init` | да |
| `secrets/` | ключи WireGuard, peer-конфиги (`chmod 600`) | да |
| `data/` | keystore ноды, данные AdGuard, SQLite ядра | keystore — да |

## Отступления от kickoff

- Флаги myst: `--udp.ports` и `--traversal` вместо устаревших `--p2p.listen.ports`,
  `--wireguard.listen.ports`, `--experiment-natpunching` ([knowledge/myst/node.md](knowledge/myst/node.md)).
- Файл Compose — `compose.yaml` (канонический), а не `docker-compose.yml`.
- Загрузчик YAML — ruamel.yaml (YAML 1.2), а не PyYAML ([knowledge/python/yamlBooleans.md](knowledge/python/yamlBooleans.md)).
- В GHCR публикуется и образ `ui` — compose ссылается на три собственных образа.
- В CI добавлены shellcheck и actionlint: в репозитории есть shell-скрипты и workflow, которые
  иначе никто не проверяет.
