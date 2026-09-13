# База знаний

Нетривиальные находки, грабли и проверенные факты (с URL источников — правило проекта §11.4).
Запись без строки в этом индексе не существует: добавили файл — добавьте и строку.

## myst

- [node.md](myst/node.md) — образ и теги, каталог данных, актуальные флаги (`--udp.ports`,
  `--traversal` вместо устаревших из kickoff), TequilAPI без аутентификации и `nodeui-pass`,
  пять GET TequilAPI для статистики и ответы свежей ноды, что известно о consumer в
  контейнере, открытый вопрос bridge vs host для provider

## adguard

- [docker.md](adguard/docker.md) — тома, `AdGuardHome.yaml` со `schema_version: 34` вместо мастера
  на 3000, ключи привязки и апстримов, порт 53 против systemd-resolved; первый старт переписывает
  файл (600, умолчания), ядро правит только свои ключи, bcrypt `$2b$` принимается, `aaaa_disabled`; перезапись имени коробки в `filtering.rewrites` — без `enabled: true` не действует; режим DNS на лету — `disable_ipv6` через API служебным пользователем ядра

## compose

- [hostNetworkAndProfiles.md](compose/hostNetworkAndProfiles.md) — что нельзя с `network_mode: host`
  (ports, networks, sysctl `net.*`), статические IP, профили, `compose.yaml` вместо `docker-compose.yml`
- [cliWrapper.md](compose/cliWrapper.md) — `--project-directory`, `--remove-orphans`, `--profile '*'`
  для `down`, двухшаговый `restart`, `.env` как производная перед `up`

## docker

- [directRouting.md](docker/directRouting.md) — транзит LAN в bridge-сеть режет цепочка DOCKER,
  `trusted_host_interfaces` не спасает; нужен `gateway_mode_ipv4=nat-unprotected` плюс свой nft-drop
  прямого доступа к адресам шлюзов (репродукция на colima)
- [bindMountRename.md](docker/bindMountRename.md) — `rename` поверх файлового bind-mount даёт EBUSY,
  монтировать каталог; права временного файла после замены — через `write_like`
- [engineOverhead.md](docker/engineOverhead.md) — сколько памяти стоит Docker: `dockerd` 87 МиБ, `containerd` 48 МиБ,
  ~10 МиБ shim на контейнер; Colima — VM поверх того же Docker, на Linux-коробке только добавит

## wireguard

- [container.md](wireguard/container.md) — модуль ядра хоста, `/dev/net/tun` только для
  wireguard-go, `src_valid_mark`, пакеты Alpine (`wg` без wg-quick); что делает entrypoint
  вместо wg-quick: ключи мимо `wg setconf`, fwmark-маршрутизация при `AllowedIPs 0.0.0.0/0`,
  kill-switch в netns контейнера, «упал» = удалён или down; ключи X25519 из `cryptography`
  с clamping как у `wg genkey` (вектор RFC 7748); пиры на работающем сервере через `wg syncconf`,
  синхронизация маршрутов, формат `wg show dump`, QR-код через `segno`
- [tunnelAccess.md](wireguard/tunnelAccess.md) — панель ноды и API ядра на адресе туннеля:
  `IP_FREEBIND` для адреса, которого ещё нет, несколько uvicorn и сигналы, NodeUI за TCP-пробросом,
  файрвол «туннельная подсеть только через wg0»

## platform

- [debianPi.md](platform/debianPi.md) — ядра Debian 12/13 и Raspberry Pi с `CONFIG_WIREGUARD=m`,
  Raspberry Pi OS на trixie; системный Python 3.11/3.13 и установка Docker из deb822-репозитория

## linux

- [iproute2Json.md](linux/iproute2Json.md) — поля `ip -j route/addr`, фикстуры для парсеров, проверка
  модуля wireguard, `is_global` против TEST-NET и CGNAT
- [doctorProbes.md](linux/doctorProbes.md) — формат `ss -lntup`, модуль через sysfs или `modprobe -n`,
  Docker включает `ip_forward` и одновременно ставит DROP на FORWARD (важно для Stage 4)
- [nftables.md](linux/nftables.md) — атомарная идемпотентная загрузка таблицы, `nft -c` требует
  NET_ADMIN, JSON-листинг для `doctor`, published-порты идут через FORWARD, `Port` в sshd — список;
  токенизация sshd_config как у sshd, `ListenAddress host:port`, `sshd -T`; DHCPv6 мимо conntrack,
  снятие таблицы парой `add table` + `delete table`
- [tunnelEgress.md](linux/tunnelEgress.md) — `accept` в своей nft-таблице не отменяет DROP от Docker,
  правила в `DOCKER-USER` по `iptables -S`, выбор бэкенда `nft`/`legacy`, NAT пиров туннеля
- [lanRouter.md](linux/lanRouter.md) — метки LAN, `ip rule` и таблицы аплинков, kill-switch маршрутом
  `unreachable` и проверка шлюза ICMP, `/proc/sys` только для чтения в `core`, формат `ip -j`
- [neighbourDevices.md](linux/neighbourDevices.md) — устройства LAN из `ip -j neigh`: состояния, кого видит
  коробка, имена из PTR вместо аренд, SQLite с версией схемы
- [gatewayContainer.md](linux/gatewayContainer.md) — шлюз с туннелем меньшего MTU подрезает TCP MSS
  (`rt mtu` в `forward`), проверка транзита и kill-switch шлюза счётчиками nft

## security

- [uiPassword.md](security/uiPassword.md) — `secrets/htpasswd` с bcrypt: почему bcrypt, проверка с
  nginx:alpine и грабля `return 200` до `auth_basic`; заменено панелью start0 (Stage 6)

## ci

- [githubActions.md](ci/githubActions.md) — мажоры actions, `setup-uv` без плавающего тега, arm64-раннеры,
  права для GHCR, ruff 0.16; тесты в контейнере на раннере: `safe.directory` и `&&` под `set -e`;
  shellcheck раннера отстаёт от локального — версия прибита с проверкой sha256
- [e2eStand.md](ci/e2eStand.md) — E2E-стенд коробки: адрес выхода вместо счётчиков туннеля, свой
  «интернет» 198.18.0.0/24, endpoint на мосту стенда, чего стенд не воспроизводит, Docker раннера

## frontend

- [toolchain.md](frontend/toolchain.md) — версии для Stage 6; TypeScript 7 против typescript-eslint,
  шаблон Vite с oxlint вместо ESLint; устарело — UI на start0
- [start0Build.md](frontend/start0Build.md) — start0 на коробке: сборка падает на 2 ГиБ (пик 2.18 ГиБ),
  runtime ~205–283 МиБ плюс Postgres ~70 МиБ, Bun на Pi 4 исправлен в v1.3.9; вход паролем коробки через
  `password.verify` по `htpasswd`, `/api/core/*` за сессией, `hostname` Bun, cookie в LAN; подмена `x-forwarded-for` обходила
  лимит — адрес сокета; вход по имени коробки в `trustedOrigins`; константа `UI_VARIANT` вырезает код только прямо в ветке

## python

- [yamlBooleans.md](python/yamlBooleans.md) — правка `config.yaml` командой: round-trip `ruamel` с отступами
  шаблона меняет одну строку и сохраняет комментарии; почему конфиг читается загрузчиком YAML 1.2
  (`ruamel.yaml`), а не PyYAML: в YAML 1.1 `mode: off` и `country: NO` — это `false`

## process

- [vibeSeed.md](process/vibeSeed.md) — откуда взят `.vibe/` (канон VibeBrains через сабмодуль
  VibeIDE), что из набора не сеется и почему
- [licensing.md](process/licensing.md) — MIT у обвязки, GPL у контейнеров: почему это агрегат,
  а не производная работа, и чего из чужих репозиториев нельзя копировать
