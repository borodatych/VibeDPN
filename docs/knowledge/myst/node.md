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
принимает: логин с этим паролем — 200, с прежним — 401; файл читается при каждой попытке
входа (первая строка), смена пароля перезапуска не требует. `myst config set
tequilapi.auth.password` — клиент к работающей ноде: пишет `config-mainnet.toml`
(`[tequilapi.auth] password = …`), но на вход это не влияет. Флаг
`--tequilapi.allowed-hostnames=.` (из e2e-compose ноды) отключает единственный фильтр Host —
защиту от DNS-rebinding, — а обращения по IP проходят и без него; в compose.yaml его нет.
**Порог Docker:** loopback-порты 4449/4050 защищены от соседей по L2 только на Engine ≥ 28.0.0
(release notes 28.0.0: «neighbor hosts to connect to ports mapped on a loopback address»);
`install.sh` и `preflight` отказываются работать со старым Engine — дистрибутивный `docker.io`
в trixie это 26.1.5.
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

## [провайдер] TequilAPI как источник статистики: шесть запросов и что отвечает свежая нода

**Контекст:** Stage 2, чекбокс 3 — `GET /provider/stats` ядра и блок `node` в `vibedpn status`.
**Суть:** сводка собирается из шести GET без аутентификации: `/healthcheck` (`version`, `uptime`
как Go-duration `6.194346087s` — для вывода дробь секунд режем), `/identities`
(`{"identities": [IdentityRefDTO]}` — **только `id`**, ничего больше: `NewIdentityListResponse`
кладёт в список `IdentityRefDTO{Address}`), `/identities/{id}` (полный IdentityDTO:
`registration_status`, `balance_tokens` / `earnings_tokens` / `earnings_total_tokens` — объекты
`Tokens {wei, ether, human}`, `wei` — строка, точное значение; 1 MYST = 10^18 wei; хендлер
`Get` при `Registered` ходит в блокчейн за каналом и может ответить 500 — тогда у identity
остаётся один `id`, причина уходит в `problems`), `/services` (массив ServiceInfoDTO: `type`,
`status`, `proposal`), `/sessions/stats-aggregated` (`{"stats": SessionStatsDTO}`: `count`,
`count_consumers`, `sum_bytes_received/sent`, `sum_duration`, `sum_tokens`),
`/node/monitoring-status` (`{"status": …}` — синхронно спрашивает quality-оракул MORQA с
минутным кэшем и 60-секундным таймаутом у ноды, поэтому обязателен только `/healthcheck`:
остальные вопросы при ошибке или таймауте 2 с деградируют к дефолтам, а причина попадает в
`problems` ответа и в строку `problems:` блока `node`). Свежая нода 1.39.5 (`daemon`, минуты после старта)
отвечает: identities `[]`, services `[]`, все суммы нулями, причём `sum_tokens` приходит
JSON-числом `0`, хотя swagger объявляет строку (`x-go-type: math/big.Int` — big.Int
сериализуется числом); Python читает такое число точно, клиент принимает и строку wei, и
число, мониторинг `unknown`. Эндпоинты `/node/provider/*` считают по identity провайдера и
до её появления бесполезны: `sessions-count` без `range` — 400 «Invalid time range»,
`transferred-data?range=1d` и `service-earnings` — 500 «identity not found» (ошибки — JSON
`{"error": {"code", "message"}, "status", "path"}`); в сводку их не берём —
`/sessions/stats-aggregated` даёт те же итоги и отвечает всегда. `uptime` из `/healthcheck` не
равен времени жизни процесса: на контейнере, поднятом 9 с назад, нода вернула `192.854845ms`
(и `321.095µs` секундами раньше) — показываем как есть, доли секунды сворачиваем в `<1s`.
Identity после `service --agreed-terms-and-conditions` появляется не сразу: через ~10 с
`/identities` всё ещё `[]`. Ответы записаны в `core/tests/fixtures/tequilapi/` и служат тестами
сборки; «занятая» нода в тестах собрана по DTO из swagger.
**Применение:** `core/vibedpn/engine/myst.py` (клиент, `ProviderStats`, рендер блока `node`),
`core/vibedpn/api/app.py` (`/provider/stats`), `core/vibedpn/api/client.py` (CLI ходит в core, а
не в ноду — одна точка входа, которая в Stage 3 уедет за туннель).
**Источники:** https://github.com/mysteriumnetwork/node/releases/download/1.39.5/swagger.json
(definitions IdentityRefDTO, IdentityDTO, Tokens, ServiceInfoDTO, SessionStatsDTO, paths `/node/*`);
https://github.com/mysteriumnetwork/node/blob/1.39.5/tequilapi/contract/identity.go
(IdentityRefDTO — одно поле `id`; `NewIdentityListResponse`),
https://github.com/mysteriumnetwork/node/blob/1.39.5/tequilapi/endpoints/identities.go
(`List` против `Get`), https://github.com/mysteriumnetwork/node/blob/1.39.5/core/quality/mysterium_morqa.go
(`MonitoringStatus`: кэш на минуту); исполнение 2026-09-12 (`mysteriumnetwork/myst:1.39.5-alpine
daemon`, busybox wget к 127.0.0.1:4050; ревью 2 линзы + скептики).

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

## [провайдер] Тип NAT ноды: `GET /nat/type` и что он значит

**Контекст:** Stage 7, проверка `nat` в `vibedpn doctor --network`, 2026-09-13.
**Суть:** в node 1.39.5 `GET /nat/type` отдаёт `{"type": ..., "error": ...}` (`tequilapi/contract/nat.go`); тип — один из `none`, `fullcone`, `rcone`, `prcone`, `symmetric` (`nat/types.go`).
Эндпоинт вызывает `natProber.Probe`: нода сама обращается к серверам Mysterium, поэтому это сетевое действие, и `doctor` спрашивает его только с `--network`.
Результат — оценка ноды, а не проверка проброса: открыт ли UDP-диапазон из интернета, видно только снаружи.
Swagger эндпоинта предупреждает, что при установленном VPN-соединении результат может быть неверным.
**Как читает `doctor`:** `none`/`fullcone` — OK; `rcone`/`prcone` — OK, но проброс `provider.udp_ports` даст больше сессий; `symmetric` — WARN и команда проброса; нет ответа — WARN.
**Источники:** https://github.com/mysteriumnetwork/node/blob/1.39.5/tequilapi/endpoints/nat.go ,
https://github.com/mysteriumnetwork/node/blob/1.39.5/tequilapi/contract/nat.go ,
https://github.com/mysteriumnetwork/node/blob/1.39.5/nat/types.go .
