# База знаний

Нетривиальные находки, грабли и проверенные факты (с URL источников — правило проекта §11.4).
Запись без строки в этом индексе не существует: добавили файл — добавьте и строку.

## myst

- [node.md](myst/node.md) — образ и теги, каталог данных, актуальные флаги (`--udp.ports`,
  `--traversal` вместо устаревших из kickoff), TequilAPI без аутентификации и `nodeui-pass`,
  пять GET TequilAPI для статистики и ответы свежей ноды, что известно о consumer в
  контейнере, открытый вопрос bridge vs host для provider; тип NAT ноды — `GET /nat/type`, оценка ноды, а не проверка проброса
- [consumer.md](myst/consumer.md) — flow consumer в node 1.39.5: identity, регистрация, `PUT /connection`,
  `kill_switch: true` выключает kill-switch, баланс не нужен при нулевой цене, образ мультиарх; пути регистрации проверены на живой ноде 20.09.2026: право — `GET /identities/{id}/eligibility`, комиссия — `GET /v2/transactor/fees`
- [sniBlocking.md](myst/sniBlocking.md) — провайдер режет TLS к `mysterium.network` по SNI: TCP открыт, рукопожатие виснет, с чужим SNI проходит; нода падает без hermes, нужен обход через свою VPS; обход без VPS: ClientHello двумя TLS-записями или имя в другом регистре — сертификат проверяется полностью
- [selfFunding.md](myst/selfFunding.md) — коробка платит сама за себя: регистрация 0.095 MYST, бесплатной сейчас нет, `referral_token` делает её бесплатной на стороне ноды; заработок нельзя выводить в свой канал, но можно в канал consumer коробки — круг без биржи, не проверен исполнением; цены задаёт сеть (WireGuard 1.72–3.83 MYST/ГиБ), нулевых нет
- [exitCheck.md](myst/exitCheck.md) — «адрес коробки» у аплинка `dpn` это не утечка: проба доктора идёт изнутри шлюза и меряет собственный трафик ноды, а он обязан быть прямым; транзит держит `policy drop` цепочки forward — доказано пробой с сети шлюзов, контроль через tor вернул адрес выхода
- [relayThrottling.md](myst/relayThrottling.md) — провайдер душит ответы Mysterium после ~16 КБ: мелкие проходят, список предложений в 7.9 МБ не приезжает никогда; разрез ClientHello спасает только рукопожатие, поэтому фильтруемое имя ретранслятор уводит в Tor (замеры, таблица путей)

## adguard

- [docker.md](adguard/docker.md) — тома, `AdGuardHome.yaml` со `schema_version: 34` вместо мастера
  на 3000, ключи привязки и апстримов, порт 53 против systemd-resolved; первый старт переписывает
  файл (600, умолчания), ядро правит только свои ключи, bcrypt `$2b$` принимается, `aaaa_disabled`; перезапись имени коробки в `filtering.rewrites` — без `enabled: true` не действует; режим DNS на лету — `disable_ipv6` через API служебным пользователем ядра
- [behindForwarder.md](adguard/behindForwarder.md) — за dnsmasq AdGuard пишет все запросы от адреса dnsmasq (`add-subnet`, `add-mac` не помогают); `ipset` — только Linux ipset, `trusted_proxies` — только DoH
- [domainUpstreams.md](adguard/domainUpstreams.md) — `[/домен/]апстрим` покрывает поддомены, кэш отсчитывает TTL своего апстрима, `querylog` отдаёт клиента, время, апстрим и `cached`
- [listFormats.md](adguard/listFormats.md) — `||домен^` покрывает домен с поддоменами, строка hosts — адрес и имена, `!` и `#` — комментарии: что читает `routing.lists`

## compose

- [hostNetworkAndProfiles.md](compose/hostNetworkAndProfiles.md) — что нельзя с `network_mode: host`
  (ports, networks, sysctl `net.*`), статические IP, профили, `compose.yaml` вместо `docker-compose.yml`
- [cliWrapper.md](compose/cliWrapper.md) — `--project-directory`, `--remove-orphans`, `--profile '*'`
  для `down`, двухшаговый `restart`, `.env` как производная перед `up`
- [extendsMerging.md](compose/extendsMerging.md) — `extends` складывает профили и заменяет монтирования по цели: проверено `docker compose config`
- [healthcheckTiming.md](compose/healthcheckTiming.md) — долгий `interval` не задерживает первую проверку при `start_period`: движок проверяет раз в `start_interval`, умолчание 5 с (Engine 25+), писать его незачем

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
- [protonFree.md](wireguard/protonFree.md) — Proton VPN Free как выход по файлу: что даёт тариф (одно
  соединение — один включённый выход), формат файла, замер на коробке: инициации уходят, ответа нет,
  адреса пингуются и TCP 443 открыт — Ростелеком режет WireGuard к Proton; чего доктор не видит

## tor

- [snowflake.md](tor/snowflake.md) — как Ростелеком режет цели (rutracker и lostfilm по имени с замерзанием после ~20 КБ,
  Telegram и rutor по адресу, ответы Mysterium через ретранслятор замирают на 16 КБ), obfs4-мосты Tor Browser не проходят,
  Snowflake проходит (~145 КБ/с), пакеты trixie без lyrebird/webtunnel, прозрачный шлюз в Tor в netns контейнера; общественный список antifilter (485 доменов) подходит `routing.lists`, открывается только с российского адреса

## ddns

- [updateAnswers.md](ddns/updateAnswers.md) — «нет» приходит и с кодом 200: DuckDNS `KO`, dyndns2 `badauth`/`nohost`/`!donator`…, dynv6 — 401; No-IP блокирует за частые `nochg`, поэтому зовём при смене адреса и раз в сутки; ipify без журналов; адрес обновления — секрет

## xray

- [realityServer.md](xray/realityServer.md) — сервер VLESS/REALITY своими силами на Xray 26.3.27: ключ — тот же X25519, что у WireGuard; `target` и `raw`; прикрытие `www.microsoft.com` не пускает никогда, `dl.google.com` — всегда, а `tls ping` этого не видит — REALITY набирает прикрытие на каждое соединение (исходник `tls.go`); отпечаток `randomized` ломает клиента; `adu`/`rmu` на ходу, им нужен порт, и они выходят с 0 даже при отказе; счётчики на человека через `/debug/vars`; закрыть людям петлю и частные сети; `libcap2-bin` тянет за собой `iproute2`; трафик сервера по uid и ответы людям мимо меток

## platform

- [debianPi.md](platform/debianPi.md) — ядра Debian 12/13 и Raspberry Pi с `CONFIG_WIREGUARD=m`,
  Raspberry Pi OS на trixie; системный Python 3.11/3.13 и установка Docker из deb822-репозитория
- [imageArchitectures.md](platform/imageArchitectures.md) — Docker v28 последний для armhf, Bun только x64/arm64: полный образ только amd64 и arm64; инструменты сборки на VM
- [piGen.md](platform/piGen.md) — ветки `pi-gen`, пользователь без пароля и переименование, своя стадия, `build-docker.sh`; cloud-init в Raspberry Pi OS trixie; действия debos и загрузчик через `run`; fakemachine видит только каталог рецепта и рабочий каталог, `/tmp` корня скрыт tmpfs nspawn, `--scratchsize`; `qemu-user` в trixie статический и pi-gen на amd64 требует `qemu-user-binfmt`; `stage2/SKIP_IMAGES` против лишнего образа Lite; у смонтированного образа симлинк с абсолютной целью проверяет ХОСТ, не образ
- [launchdExternalVolume.md](platform/launchdExternalVolume.md) — фоновому заданию macOS внешний том недоступен целиком (чтение, запись, запуск), отказ немой: журнал на том же томе не пишется; вторая мина — `Include` в личном `~/.ssh/config`, указывающий на внешний том, валит ssh до старта

## linux

- [hostapdControl.md](linux/hostapdControl.md) — управляющий сокет hostapd: `ATTACH`, события `AP-STA-*`, перебор станций, общий каталог сокета двух контейнеров и молчание после перезапуска
- [systemdPathUnit.md](linux/systemdPathUnit.md) — `.path` по изменению файла: `PathChanged=` на закрытие после записи, чего документация не обещает и как это обойдено
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
- [dnsmasqLeases.md](linux/dnsmasqLeases.md) — формат файла аренд dnsmasq (время, MAC, адрес, имя, client-id),
  снят исполнением на 2.92; как собрать образ для опыта без сети
- [hostapdConfigCheck.md](linux/hostapdConfigCheck.md) — hostapd 2.11 без радио: ошибка конфига (`errors found in configuration file`) отличима от ошибки драйвера; виртуальное радио `mac80211_hwsim` для стенда
- [dnsmasqNftset.md](linux/dnsmasqNftset.md) — `--nftset` есть в справке, но Alpine 3.24 собирает dnsmasq с `no-nftset`; Debian trixie — с `nftset`
- [boxBackup.md](linux/boxBackup.md) — `tarfile` без фильтров в bookworm (3.11.2), `compose pull --ignore-buildable`, `compose pull` не трогает выключенные профили, а `up` запускает старый образ, если он уже лежит, ключи таймера systemd, AdGuard не от root на порту 53 (`NET_BIND_SERVICE`)
- [githubBlackholedAddress.md](linux/githubBlackholedAddress.md) — обновление коробки висит 133 с: один из адресов GitHub у провайдера — чёрная дыра, резолвер отдаёт его через раз; лечится таймаутом на попытку и повторами с новым резолвом

## security

- [uiPassword.md](security/uiPassword.md) — `secrets/htpasswd` с bcrypt: почему bcrypt, проверка с
  nginx:alpine и грабля `return 200` до `auth_basic`; заменено панелью start0 (Stage 6); пароль Wi-Fi, однажды напечатанный в сессию, оставлен как есть — решение владельца 20.09.2026, правило «секреты в сессию не печатать»
- [fail2ban.md](security/fail2ban.md) — служба `active` и джейл `sshd` ничего не говорят о том, что
  бан работает: `reload` со сменой `banaction` оставляет джейл без действий, таблица `f2b-table`
  появляется только с первым баном, сквозная проверка — с адреса контейнера, а не своего

## ci

- [githubActions.md](ci/githubActions.md) — мажоры actions, `setup-uv` без плавающего тега, arm64-раннеры,
  права для GHCR, ruff 0.16; тесты в контейнере на раннере: `safe.directory` и `&&` под `set -e`;
  shellcheck раннера отстаёт от локального — версия прибита с проверкой sha256
- [e2eStand.md](ci/e2eStand.md) — E2E-стенд коробки: адрес выхода вместо счётчиков туннеля, свой
  «интернет» 198.18.0.0/24, endpoint на мосту стенда, чего стенд не воспроизводит, Docker раннера; стенд Wi-Fi — в VM Debian 13 под KVM: в ядре раннера (Azure) нет `mac80211_hwsim`

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
- [deeperPanel.md](process/deeperPanel.md) — панель Deeper Connect изнутри: 144 пути API, режимы smart/full/direct,
  туннель = страна, белый и чёрный списки доменов, сутки: потреблено 27 ГБ при 45 МБ розданных — доступ не завязан на раздачу
- [licensing.md](process/licensing.md) — MIT у обвязки, GPL у контейнеров: почему это агрегат,
  а не производная работа, и чего из чужих репозиториев нельзя копировать
