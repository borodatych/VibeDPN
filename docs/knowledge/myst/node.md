# Mysterium node (`myst`) в Docker

Проверено по официальным источникам 2026-09-11 (Stage 0). Часть фактов §10 kickoff устарела —
см. первую запись.

## [баг] Флаги портов и NAT из kickoff устарели

**Контекст:** kickoff §10 называл `--p2p.listen.ports`, `--wireguard.listen.ports`,
`--experiment-natpunching=false` и диапазоны 41920-42075 / 61920-62075.
**Суть:** в `config/flags_network.go` мастера один флаг `--udp.ports=start:end` (по умолчанию
`10000:60000`); `--p2p.listen.ports` и `--wireguard.listen.ports` помечены «Deprecated flag, use
--udp.ports»; вместо `--nat-hole-punching` (алиас `--experiment-natpunching`) и `--nat-port-mapping`
— `--traversal=manual,upnp,holepunching` (порядок методов). Гайд по роутерам велит пробрасывать
UDP 56000-56100, поэтому в конфиге по умолчанию `udp_ports: "56000-56100"` и флаг
`--udp.ports=56000:56100`; несоответствие гайда и дефолта 10000:60000 описано в issue #6064.
**Применение:** compose.yaml и `provider` в config.yaml; Stage 2 и 7.
**Источники:** https://raw.githubusercontent.com/mysteriumnetwork/node/master/config/flags_network.go ,
https://help.mystnodes.com/en/articles/8591945 (проброс 56000-56100),
https://github.com/mysteriumnetwork/node/issues/6064 .

## [баг] Глобальные флаги — только перед командой

**Контекст:** первая версия compose.yaml ставила `--udp.ports` и `--tequilapi.*` после `service`,
как в старых гайдах с `SERVICE_OPTS`.
**Суть:** `myst --help` образа 1.39.5-alpine относит `--udp.ports`, `--traversal`, `--ui.enable`,
`--ui.port`, `--firewall.killSwitch.always`, `--tequilapi.address/port/allowed-hostnames`,
`--data-dir` к GLOBAL OPTIONS; у команды `service` свой флаг только `--agreed-terms-and-conditions`,
у `daemon` своих нет. Проверено запуском с `--help` (нода не стартует): `myst service
--udp.ports=… --help` → «Incorrect Usage: flag provided but not defined: -udp.ports»; `myst
--udp.ports=… service --help` → штатная справка. То же для `daemon --firewall.killSwitch.always`.
**Применение:** `command:` в compose.yaml — сначала глобальные флаги, потом `service`/`daemon`.
Проверять новые флаги той же связкой `--help`, а не запуском ноды.
**Источники:** `docker run --rm --entrypoint myst mysteriumnetwork/myst:1.39.5-alpine --help`
(2026-09-11); https://raw.githubusercontent.com/mysteriumnetwork/node/master/config/flags_network.go .

## [провайдер] Образ, теги, arm64, каталог данных

**Суть:** Docker Hub `mysteriumnetwork/myst`; теги `latest`, `latest-alpine`, `<версия>-alpine`
(простого `<версия>` без суффикса нет — `tags/1.39.5` отдаёт 404). Манифест multi-arch:
linux/amd64, linux/arm64, linux/arm/v7 — community-сборка под arm64 не нужна. Актуальный
релиз 1.39.5 (2026-08-17) → `mysteriumnetwork/myst:1.39.5-alpine`. Данные ноды (keystore,
конфиг, логи) — `/var/lib/mysterium-node`, его и монтируем; entrypoint сам передаёт
`--data-dir`, `--config-dir`, `--runtime-dir`, `--script-dir`, аргументы контейнера идут после.
Образ **не обновляет себя** (авто-апдейт есть только у deb-пакета) — обновление = pull + пересоздать
с тем же volume.
**Источники:** https://hub.docker.com/v2/repositories/mysteriumnetwork/myst/tags?page_size=15 ,
https://raw.githubusercontent.com/mysteriumnetwork/node/master/bin/docker/docker-entrypoint.sh ,
https://raw.githubusercontent.com/mysteriumnetwork/node/master/README.md .

## [провайдер] Как официально запускают provider

**Суть:** `docker run --cap-add NET_ADMIN -d -p 4449:4449 --name myst -v $DIR:/var/lib/mysterium-node
--restart unless-stopped mysteriumnetwork/myst:latest service --agreed-terms-and-conditions`.
Без `--agreed-terms-and-conditions` (и без сохранённого согласия) процесс выходит с кодом 2.
e2e-compose репозитория добавляет `devices: [/dev/net/tun]`; sysctl для provider не задают. Мультинодовый
гайд (2026-03) запускает provider на bridge-сети со статическим IP и iptables SNAT — без `--net host`;
при этом `INSTALL.md` всё ещё говорит, что `--net host` обязателен для определения IP сервиса.
**Открытые вопросы для Stage 2 (из критика исследования, официального ответа нет):** нужно ли
публиковать UDP-диапазон в bridge-режиме или хватает hole punching; работает ли UPnP из
bridge-контейнера (SSDP-multicast через docker-bridge не ходит — вероятно, `--traversal` без
`upnp` или host-сеть для provider); 101 опубликованный UDP-порт = 101 процесс `docker-proxy`
(на Raspberry Pi — память; альтернатива `"userland-proxy": false` в daemon.json или host-сеть);
использует ли нода kernel-WireGuard через netlink или userspace (в e2e монтируют `/dev/net/tun`
и для provider, и для consumer — монтируем тоже). Проверять на реальной VPS.
**Источники:** https://help.mystnodes.com/en/articles/3777670-running-a-mystnodes-as-docker-image-on-linux-host ,
https://help.mystnodes.com/en/articles/13924892 (multi-node compose),
https://raw.githubusercontent.com/mysteriumnetwork/node/master/cmd/commands/service/command.go .

## [баг] TequilAPI не аутентифицирует; пароль NodeUI — файл `nodeui-pass`

**Контекст:** Stage 2, чекбокс 1; хотели «пароль TequilAPI из secrets вместо myst/mystberry».
**Суть:** проверено исполнением на 1.39.5-alpine (`daemon`, без `service`): `GET /identities`,
`/connection`, `/sessions`, `/config`, `/proposals` отвечают 200 без токена — JWT из
`POST /auth/login` защищает только NodeUI и `/auth/*`. Значит, «пароль TequilAPI» ничего не
охраняет; охраняет только сеть: provider публикует 4050 на `127.0.0.1`, consumer (Stage 8) на
10.77.0.20 обязан быть закрыт nft от LAN. Пароль NodeUI хранится в `<data-dir>/nodeui-pass` —
bcrypt-хеш (60 байт, 600); при отсутствии файла нода при старте пишет туда хеш `mystberry`
(лог: «CredentialsManager not found, initializing to default»). Файл с нашим `$2b$`-хешем нода
принимает: логин с этим паролем — 200, с прежним — 401. `myst config set
tequilapi.auth.password` — клиент к работающей ноде: пишет `config-mainnet.toml`
(`[tequilapi.auth] password = …`), но на вход это не влияет.
**Применение:** `init` пишет `data/myst-provider/nodeui-pass` с bcrypt пароля панелей;
`config.toml` не трогаем. Core в чекбоксе 3 ходит в TequilAPI без учётных данных.
**Источники:** исполнение 2026-09-12 (`docker run … daemon`, busybox wget к 127.0.0.1:4050);
https://github.com/mysteriumnetwork/node/blob/master/core/auth/credentials.go (CredentialsManager).

## [провайдер] TequilAPI и NodeUI

**Суть:** TequilAPI слушает `127.0.0.1:4050`; флаги `--tequilapi.address`, `--tequilapi.port`,
`--tequilapi.allowed-hostnames` (allowlist заголовка Host, по умолчанию `.localhost, localhost,
.localdomain`; e2e-compose открывает наружу контейнера через `--tequilapi.address=0.0.0.0
--tequilapi.allowed-hostnames=.`), логин по умолчанию `--tequilapi.auth.username=myst`
`--tequilapi.auth.password=mystberry` — **Stage 2 обязан сменить**. NodeUI: `--ui.port` (4449),
`--ui.enable=false` выключает, `--ui.address` задаёт адреса. Хостинг Swagger
`tequilapi.mysterium.network` не резолвится (2026-09-11); спека — asset релиза `swagger.json`
или `http://127.0.0.1:4050/docs` у самой ноды.
**Источники:** https://raw.githubusercontent.com/mysteriumnetwork/node/master/config/flags_node.go ,
https://raw.githubusercontent.com/mysteriumnetwork/node/master/config/flags_ui.go ,
https://github.com/mysteriumnetwork/node/releases/download/1.39.5/swagger.json .

## [провайдер] Consumer в контейнере — что известно (для Stage 8)

**Суть:** команда контейнера `daemon`; kill-switch — флаг `--firewall.killSwitch.always`
(только Linux, добавлен ради Docker-consumer'ов, issue #3924 открыт); подключение —
`myst connection up --agreed-terms-and-conditions` (флаги `--tequilapi.address/--tequilapi.port`),
подкоманды `proposals/up/down/info`. e2e-consumer'ы ставят sysctl `net.ipv6.conf.all.disable_ipv6=0`.
Официального описания поведения consumer'а с default route и DNS в контейнере нет — только
e2e/localnet compose и `prepare-run-env.sh`. Минимальные требования ноды: 1 ядро, 1 ГБ RAM, 500 МБ.
Лицензия репозитория — GPL-3.0.
**Источники:** https://raw.githubusercontent.com/mysteriumnetwork/node/master/cmd/commands/connection/command.go ,
https://github.com/mysteriumnetwork/node/issues/3924 ,
https://help.mystnodes.com/en/articles/8006183-mystnodes-installation-guide-on-linux-full ,
https://api.github.com/repos/mysteriumnetwork/node .
