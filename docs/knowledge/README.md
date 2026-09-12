# База знаний

Нетривиальные находки, грабли и проверенные факты (с URL источников — правило проекта §11.4).
Запись без строки в этом индексе не существует: добавили файл — добавьте и строку.

## myst

- [node.md](myst/node.md) — образ и теги, каталог данных, актуальные флаги (`--udp.ports`,
  `--traversal` вместо устаревших из kickoff), TequilAPI и NodeUI, что известно о consumer в
  контейнере, открытый вопрос bridge vs host для provider

## adguard

- [docker.md](adguard/docker.md) — тома, `AdGuardHome.yaml` со `schema_version: 34` вместо мастера
  на 3000, ключи привязки и апстримов, порт 53 против systemd-resolved

## compose

- [hostNetworkAndProfiles.md](compose/hostNetworkAndProfiles.md) — что нельзя с `network_mode: host`
  (ports, networks, sysctl `net.*`), статические IP, профили, `compose.yaml` вместо `docker-compose.yml`
- [cliWrapper.md](compose/cliWrapper.md) — `--project-directory`, `--remove-orphans`, `--profile '*'`
  для `down`, двухшаговый `restart`, `.env` как производная перед `up`

## docker

- [directRouting.md](docker/directRouting.md) — транзит LAN в bridge-сеть режет цепочка DOCKER,
  `trusted_host_interfaces` не спасает; нужен `gateway_mode_ipv4=nat-unprotected` плюс свой nft-drop
  прямого доступа к адресам шлюзов (репродукция на colima)

## wireguard

- [container.md](wireguard/container.md) — модуль ядра хоста, `/dev/net/tun` только для
  wireguard-go, `src_valid_mark`, пакеты Alpine (`wg` без wg-quick)

## platform

- [debianPi.md](platform/debianPi.md) — ядра Debian 12/13 и Raspberry Pi с `CONFIG_WIREGUARD=m`,
  Raspberry Pi OS на trixie; системный Python 3.11/3.13 и установка Docker из deb822-репозитория

## linux

- [iproute2Json.md](linux/iproute2Json.md) — поля `ip -j route/addr`, фикстуры для парсеров, проверка
  модуля wireguard, `is_global` против TEST-NET и CGNAT
- [doctorProbes.md](linux/doctorProbes.md) — формат `ss -lntup`, модуль через sysfs или `modprobe -n`,
  Docker включает `ip_forward` и одновременно ставит DROP на FORWARD (важно для Stage 4)

## security

- [uiPassword.md](security/uiPassword.md) — `secrets/htpasswd` с bcrypt: почему bcrypt, проверка с
  nginx:alpine и грабля `return 200` до `auth_basic`

## ci

- [githubActions.md](ci/githubActions.md) — мажоры actions, `setup-uv` без плавающего тега, arm64-раннеры,
  права для GHCR, ruff 0.16; тесты в контейнере на раннере: `safe.directory` и `&&` под `set -e`

## frontend

- [toolchain.md](frontend/toolchain.md) — версии для Stage 6; TypeScript 7 против typescript-eslint,
  шаблон Vite с oxlint вместо ESLint

## python

- [yamlBooleans.md](python/yamlBooleans.md) — почему конфиг читается загрузчиком YAML 1.2
  (`ruamel.yaml`), а не PyYAML: в YAML 1.1 `mode: off` и `country: NO` — это `false`

## process

- [vibeSeed.md](process/vibeSeed.md) — откуда взят `.vibe/` (канон VibeBrains через сабмодуль
  VibeIDE), что из набора не сеется и почему
- [licensing.md](process/licensing.md) — MIT у обвязки, GPL у контейнеров: почему это агрегат,
  а не производная работа, и чего из чужих репозиториев нельзя копировать
