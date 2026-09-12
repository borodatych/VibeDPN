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
| Каталог | `/opt/vibedpn` — клон репозитория (`install.sh`); там же `venv/` с CLI, симлинк `/usr/local/bin/vibedpn`; рядом `config.yaml`, `.env`, `secrets/`, `data/` |

## Стек

| Слой | Технологии | Версии |
|---|---|---|
| `core/` | Python, FastAPI, Pydantic v2, Typer, httpx, Jinja2, ruamel.yaml (YAML 1.2), uvicorn | `requires-python >= 3.11`: CLI на коробке работает на системном Python (bookworm 3.11.2, trixie 3.13.5), образ `core` — 3.12; fastapi 0.141, pydantic 2.13, typer 0.27, uvicorn 0.52 — точные версии в `core/uv.lock`, для установки без uv — `core/requirements.txt` с sha256 |
| Тулчейн core | uv, ruff, mypy strict + плагин pydantic, pytest | uv 0.12.13, ruff 0.16.7, mypy 2.3.1, pytest 9.1.1 |
| `images/wg/` | Alpine + `wireguard-tools-wg` + `iproute2` + `nftables` | alpine 3.24 |
| `ui/` | React + TypeScript strict + Vite + Tailwind + shadcn/ui + Zustand, отдаёт nginx | react 19.3, vite 8.3, TypeScript **6.0.x** (typescript-eslint не поддерживает 7), tailwind 4.3, node 24 (Active LTS) — Stage 6 |
| CI | GitHub Actions: ruff, mypy, pytest, shellcheck, actionlint, `compose config`, buildx multi-arch → GHCR | checkout v7, setup-uv v10.1.0, setup-node v7, docker/* v4/v6/v7 |

## Образы

| Образ | Откуда | Тег |
|---|---|---|
| `ghcr.io/borodatych/vibedpn-core` | `core/Dockerfile`, `python:3.12-slim-trixie`, зависимости из `uv.lock` | `${VIBEDPN_TAG}` (`latest` = main, `next`, `sha-…`, semver из тегов `v*`) |
| `ghcr.io/borodatych/vibedpn-wg` | `images/wg/Dockerfile`, `alpine:3.24` | `${VIBEDPN_TAG}` |
| `ghcr.io/borodatych/vibedpn-ui` | `ui/Dockerfile`, `nginx:1.31-alpine` (mainline) | `${VIBEDPN_TAG}` |
| `mysteriumnetwork/myst` | Docker Hub, multi-arch amd64/arm64/arm-v7 | `1.39.5-alpine` (`${MYST_TAG}`) |
| `adguard/adguardhome` | Docker Hub, multi-arch | `v0.107.79` (`${ADGUARD_TAG}`) |

## Сервисы `compose.yaml`

| Сервис | Профиль | Сеть | Порты и особенности |
|---|---|---|---|
| `core` | всегда | host, `NET_ADMIN` | API на `127.0.0.1:${VIBEDPN_API_PORT}` (4480); монтирует `config.yaml` (ro), `secrets/`, `data/core`; healthcheck `GET /health` |
| `ui` | `ui` | host | nginx на `${VIBEDPN_LAN_IP}:${VIBEDPN_UI_PORT}` (80), `/api/` → core; зависит от здорового `core`. Авторизация `/api/` (auth_basic, пароль из `init`) — Stage 4, до первого изменяющего эндпоинта |
| `myst-provider` | `provider` | bridge | `127.0.0.1:4449` NodeUI, `127.0.0.1:4050` TequilAPI, UDP `${VIBEDPN_MYST_UDP_FROM}-${VIBEDPN_MYST_UDP_TO}` (56000-56100); `myst --udp.ports=… --traversal=… --tequilapi.* service --agreed-terms-and-conditions` (глобальные флаги — до команды); том `data/myst-provider` |
| `myst-consumer` | `consumer` | `vibedpn-upstreams` 10.77.0.20, `NET_ADMIN`, `ip_forward=1` | `myst --firewall.killSwitch.always --ui.enable=false --tequilapi.* daemon`; том `data/myst-consumer` |
| `wg-client` | `wg-client` | `vibedpn-upstreams` 10.77.0.10, `NET_ADMIN`, `ip_forward=1`, `src_valid_mark=1` | `secrets/wg-client.conf` (кладёт `init --peer-config`) → `/etc/wireguard/wg0.conf`; entrypoint `client` (Stage 3) |
| `wg-server` | `wg-server` | host, `NET_ADMIN` | `secrets/wg-server/` → `/etc/wireguard`; UDP 51820 открывает nft-baseline core; entrypoint `server` (Stage 3) |
| `adguard` | `dns` | host | тома `data/adguard/{work,conf}`; `AdGuardHome.yaml` рендерит core (Stage 4), веб-панель на `${VIBEDPN_LAN_IP}:3000` |

Сеть `vibedpn-upstreams` — `10.77.0.0/24`, bridge со статическими адресами шлюзов в режиме
`gateway_mode_ipv4=nat-unprotected`: иначе цепочка `DOCKER` режет любой транзит в бридж с других
интерфейсов хоста. Плата за режим — Docker не фильтрует порты контейнеров, поэтому router-engine
(Stage 4) сам запрещает LAN прямой доступ к `10.77.0.0/24`
([knowledge/docker/directRouting.md](knowledge/docker/directRouting.md)).

## Файлы на коробке

| Путь | Что | В бэкап |
|---|---|---|
| `config.yaml` | единственный источник правды ([manuals/configSpec.md](manuals/configSpec.md)) | да |
| `.env` | производные для compose + `VIBEDPN_TAG`; пишет `init` | да |
| `secrets/` | `htpasswd` (bcrypt пароля UI), `wg-client.conf` (peer-файл), ключи WireGuard — 600 внутри 700 | да |
| `config.yaml.bak` | предыдущий конфиг после `init --force` | нет |
| `data/` | keystore ноды и `myst-provider/nodeui-pass` (bcrypt пароля панели), данные AdGuard, SQLite ядра | keystore и `nodeui-pass` — да |

## Отступления от kickoff

- Флаги myst: `--udp.ports` и `--traversal` вместо устаревших `--p2p.listen.ports`,
  `--wireguard.listen.ports`, `--experiment-natpunching` ([knowledge/myst/node.md](knowledge/myst/node.md)).
- Файл Compose — `compose.yaml` (канонический), а не `docker-compose.yml`.
- Загрузчик YAML — ruamel.yaml (YAML 1.2), а не PyYAML ([knowledge/python/yamlBooleans.md](knowledge/python/yamlBooleans.md)).
- В GHCR публикуется и образ `ui` — compose ссылается на три собственных образа.
- В CI добавлены shellcheck и actionlint: в репозитории есть shell-скрипты и workflow, которые
  иначе никто не проверяет.
