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
| `core/` | Python, FastAPI, Pydantic v2, Typer, httpx, Jinja2, ruamel.yaml (YAML 1.2), uvicorn, cryptography (X25519 для ключей WireGuard), segno (QR-код файла пира в терминале) | `requires-python >= 3.11`: CLI на коробке работает на системном Python (bookworm 3.11.2, trixie 3.13.5), образ `core` — 3.12; fastapi 0.141, pydantic 2.13, typer 0.27, uvicorn 0.52 — точные версии в `core/uv.lock`, для установки без uv — `core/requirements.txt` с sha256 |
| Тулчейн core | uv, ruff, mypy strict + плагин pydantic, pytest | uv 0.12.13, ruff 0.16.7, mypy 2.3.1, pytest 9.1.1 |
| `images/wg/` | Alpine + `wireguard-tools-wg` + `iproute2` + `nftables` | alpine 3.24 |
| `ui/` | start0: Point0 + Prisma + better-auth на Bun, Postgres 17; варианты `full`/`lite` — [uiVariants.md](uiVariants.md) | пак start0 v0.1.23, `oven/bun:1.4.2`, `postgres:17.11-alpine`, TypeScript 7 (`bun run check`) |
| CI | GitHub Actions: ruff, mypy, pytest, shellcheck, actionlint, `compose config`, buildx multi-arch → GHCR | checkout v7, setup-uv v10.1.0, setup-node v7, docker/* v4/v6/v7 |

## Образы

| Образ | Откуда | Тег |
|---|---|---|
| `ghcr.io/borodatych/vibedpn-core` | `core/Dockerfile`, `python:3.12-slim-trixie`, зависимости из `uv.lock`; из Debian `nftables` и `wireguard-tools` | `${VIBEDPN_TAG}` (`latest` = main, `next`, `sha-…`, semver из тегов `v*`) |
| `ghcr.io/borodatych/vibedpn-wg` | `images/wg/Dockerfile`, `alpine:3.24` | `${VIBEDPN_TAG}` |
| `ghcr.io/borodatych/vibedpn-ui` | `ui/Dockerfile`: сборка `dist` на платформе сборки, runtime `oven/bun:1.4.2` на amd64 и arm64 | `${VIBEDPN_TAG}-full` / `-lite` (`ui.variant` → `VIBEDPN_UI_VARIANT`; `--build-arg UI_VARIANT`) |
| `mysteriumnetwork/myst` | Docker Hub, multi-arch amd64/arm64/arm-v7 | `1.39.5-alpine` (`${MYST_TAG}`) |
| `adguard/adguardhome` | Docker Hub, multi-arch | `v0.107.79` (`${ADGUARD_TAG}`) |

## Сервисы `compose.yaml`

| Сервис | Профиль | Сеть | Порты и особенности |
|---|---|---|---|
| `core` | всегда | host, `NET_ADMIN` | API на `127.0.0.1:${VIBEDPN_API_PORT}` (4480): `GET /health`, `GET /status` (режим, аплинки: шлюз отвечает или нет по наблюдателю ядра, маршруты шлюза и kill-switch, итог `lan_without_exit`; 404 без LAN), `PUT /routing` (`mode` off|full и/или `default_upstream`: запись `config.yaml`, роутер на месте с откатом, затем AdGuard через свой API — `adguard: applied|pending|none`), `GET /provider/stats` (сводка ноды из TequilAPI `127.0.0.1:4050`; 404 без провайдера в роли, 503 когда нода не отвечает), `GET /peers`, `POST /peers`, `GET /peers/{name}/config`, `DELETE /peers/{name}` (пиры туннеля на vps: 404 без сервера, 409 повтор имени или кончилась подсеть, 422 плохое имя; закрытый ключ пира — только в выгрузке его файла; живое состояние пиров — из `wg show wg0 dump` хоста); на vps ещё слушает адрес сервера туннеля через `IP_FREEBIND`: `${VIBEDPN_API_PORT}` — только `GET /health` и `GET /provider/stats` и только с адресов туннеля, 4449 — TCP-проброс на панель ноды `127.0.0.1:4449`; монтирует `config.yaml` (ro), `secrets/`, `data/core`; healthcheck `GET /health`; на vps при старте применяет nftables-таблицу `inet vibedpn` (с `wg0` — только 4449 и порт API, подсеть туннеля не через `wg0` — drop) |
| `ui` | `ui` | host | приложение на `${VIBEDPN_LAN_IP}:${VIBEDPN_UI_PORT}` (80), только этот адрес; вход паролем из `init` (bcrypt из `secrets/htpasswd` на каждом входе) со страницы по адресу или по `ui.host_name` (`VIBEDPN_UI_HOST_NAME`), лимит — 5 попыток за 5 минут по адресу сокета, `/api/core/*` → core на `127.0.0.1:${VIBEDPN_API_PORT}` только с сессией; монтирует `htpasswd`, `ui-db-password`, `ui-auth-secret` (ro); зависит от здоровых `core` и `ui-db`; healthcheck `GET /api/health` |
| `ui-db` | `ui` | bridge | `postgres:17.11-alpine`, `127.0.0.1:${VIBEDPN_UI_DB_PORT}` (5480); пароль `POSTGRES_PASSWORD_FILE`; данные `data/ui-db`; `shared_buffers`/`max_connections` из `VIBEDPN_UI_DB_*` (у `lite` — 32MB и 20, иначе умолчания Postgres) |
| `myst-provider` | `provider` | bridge | `127.0.0.1:4449` NodeUI, `127.0.0.1:4050` TequilAPI, UDP `${VIBEDPN_MYST_UDP_FROM}-${VIBEDPN_MYST_UDP_TO}` (56000-56100); `myst --udp.ports=… --traversal=… --tequilapi.* service --agreed-terms-and-conditions` (глобальные флаги — до команды); том `data/myst-provider` |
| `myst-consumer` | `consumer` | `vibedpn-upstreams` 10.77.0.20, `NET_ADMIN`, `ip_forward=1` | `myst --firewall.killSwitch.always --ui.enable=false --tequilapi.* daemon`; том `data/myst-consumer` |
| `wg-client` | `wg-client` | `vibedpn-upstreams` 10.77.0.10, `NET_ADMIN`, `ip_forward=1`, `src_valid_mark=1` | `secrets/wg-client.conf` (кладёт `init --peer-config`) → `/etc/wireguard/wg0.conf`; entrypoint `client`: wg0 + маршруты по `AllowedIPs`, при `0.0.0.0/0` — fwmark 51820 и таблица 51820, kill-switch (ставится до создания интерфейса) и MASQUERADE в netns контейнера; метка `FwMark` приходит из конфига, `PersistentKeepalive` проставляется пирам без него; сторож следит за интерфейсом и возрастом handshake; healthcheck — свежий handshake |
| `wg-server` | `wg-server` | host, `NET_ADMIN` | `secrets/wg-server/` → `/etc/wireguard`: `server.key` и `wg0.conf` пишет `core` при каждом старте, поэтому сервис ждёт здорового `core`; UDP 51820 открывает nft-baseline core; entrypoint `server`: wg0, адрес и маршруты пиров, файрвола нет; healthcheck — интерфейс поднят |
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
| `secrets/` | `htpasswd` (bcrypt пароля коробки: панель, API ядра, AdGuard), `adguard-core-password` (служебный пользователь ядра `vibedpn-core` в AdGuard: меняет режим DNS на лету; только при `dns`), `ui-db-password` и `ui-auth-secret` (пароль базы панели и ключ сессий; `init` создаёт один раз и не перетирает), `wg-client.conf` (peer-файл), на vps — `wg-server/server.key` (ключ сервера туннеля, генерирует `core` один раз) и `wg-server/wg0.conf` (рендер из `config.yaml` и реестра пиров), `wg-server/peers.json` (реестр пиров с их ключами, пишет только `core`); всё 600 внутри 700 | да — `server.key` обязательно: без него все домашние коробки придётся переподключать |
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
