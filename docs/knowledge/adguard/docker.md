# AdGuard Home в Docker

## [провайдер] Образ, тома, конфиг без мастера настройки

**Контекст:** Stage 4 рендерит конфиг AdGuard из config.yaml; compose.yaml Stage 0 монтирует тома.
**Суть:** образ `adguard/adguardhome`, теги `latest` (stable), `beta`, `edge`, версионные `vX.Y.Z`;
актуальный stable v0.107.79 (2026-08-18); манифест multi-arch (amd64, arm64, arm/v6, arm/v7, 386,
ppc64le). Тома: `/opt/adguardhome/work` (данные) и `/opt/adguardhome/conf` (конфиг). CMD образа:
`--no-check-update -c /opt/adguardhome/conf/AdGuardHome.yaml -w /opt/adguardhome/work`.
Первый запуск определяется **только** наличием файла по `-c` (`detectFirstRun` = `os.Stat`) — заранее
положенный `AdGuardHome.yaml` пропускает мастер на порту 3000; `/install.html` тогда редиректит на `/`.
В файле обязателен `schema_version: 34` (текущий; отсутствие = 0 → все миграции и перезапись файла,
больше 34 → отказ старта). Ключи: `dns.bind_hosts` (список IP, слушать только LAN-адрес),
`dns.port`, `http.address` (`host:port`; старые `bind_host/bind_port` устарели),
`dns.upstream_dns` (`https://…/dns-query`, также `tls://`, `quic://`, `h3://`), `dns.bootstrap_dns`.
**Применение:** host network обязателен для DHCP и даёт реальные IP клиентов; порт 53 на хосте
с systemd-resolved занят stub-listener'ом — лечится `DNSStubListener=no` в
`/etc/systemd/resolved.conf.d/` или привязкой только к LAN-адресу (наш путь).
**Факты исполнением (v0.107.79, 2026-09-13):** хеш bcrypt `$2b$` из Python `bcrypt` (его пишет
`init`) AdGuard принимает в `users[].password`: `/control/login` — 200 с верным паролем, 403 с
неверным. `dns.aaaa_disabled: true` — ответ на AAAA пустой (0 записей), на A — обычный. Первый старт
**переписывает** файл: все умолчания раскрыты (~187 строк), права `600` от root, комментарии выброшены,
`schema_version` в конце; повторные старты файл не трогают, а ключ, изменённый между стартами,
применяется. Отсюда устройство `engine/adguard.py`: ядро до старта AdGuard (`depends_on`) пишет
минимальный файл, если его нет, а иначе round-trip-правкой меняет только свои ключи — фильтры из UI
живут. Грабля round-trip: `ruamel` пишет `None` пустым значением (`protection_disabled_until:`), а
AdGuard — `null`; представление `None` задано явно, иначе правка трогала чужой ключ (поймал тест на
реальном переписанном файле). Недоступный `http.address` роняет только веб-интерфейс (panic
перехвачен), DNS и запись файла работают. Настройки AdGuard применяются только перезапуском
контейнера — `vibedpn mode` перезапускает и его, но **после** ядра: `compose restart core adguard`
перезапускает оба сразу, не дожидаясь здоровья, и AdGuard стартовал на старом файле (smoke: в `off`
AAAA оставался пустым). Порядок — `restart core`, `up -d --no-deps --wait core` («Wait for services
to be running|healthy», https://docs.docker.com/reference/cli/docker/compose/up/), `restart adguard`.
**Источники:** https://hub.docker.com/r/adguard/adguardhome ,
https://raw.githubusercontent.com/AdguardTeam/AdGuardHome/v0.107.79/docker/build.Dockerfile ,
https://raw.githubusercontent.com/AdguardTeam/AdGuardHome/v0.107.79/internal/home/home.go ,
https://raw.githubusercontent.com/AdguardTeam/AdGuardHome/v0.107.79/internal/configmigrate/configmigrate.go ,
https://adguard-dns.io/kb/adguard-home/configuration/ , https://adguard-dns.io/kb/adguard-home/faq/ ,
https://github.com/AdguardTeam/AdGuardHome/releases/latest .

## [провайдер] Перезапись имени коробки: `filtering.rewrites` и обязательный `enabled`

**Контекст:** Stage 6, имя панели `ui.host_name` (`engine/adguard.py`), 2026-09-13.
**Суть:** перезаписи DNS живут в `filtering.rewrites` (с v0.107.37, раньше — `dns.rewrites`), запись — `domain` и `answer`.
Документация поле `enabled` не называет, но в v0.107.79 записи конфига — `LegacyRewrite` с `Enabled bool yaml:"enabled"`, и `findRewrites` пропускает запись с `!e.Enabled`: без `enabled: true` своя запись молча не действует.
AdGuard выбрасывает незнакомые ключи и комментарии, поэтому, какая перезапись принадлежит ядру, файл сказать не может: последнее опубликованное имя ядро хранит в `data/core/adguard-host-name` и при переименовании снимает запись с прежним именем.
**Источники:** https://github.com/AdguardTeam/AdGuardHome/wiki/Configuration ,
https://github.com/AdguardTeam/AdGuardHome/blob/v0.107.79/internal/filtering/rewrites.go ,
https://github.com/AdguardTeam/AdGuardHome/blob/v0.107.79/internal/filtering/rewrite/item.go .

## [провайдер] Режим DNS на лету: `disable_ipv6` через API и служебный пользователь ядра

**Контекст:** Stage 6, экран статуса и `PUT /routing` (`engine/adguard.py`), 2026-09-13.
**Суть:** AdGuard читает `dns.aaaa_disabled` из файла только при старте, поэтому `vibedpn mode` раньше перезапускал его через Compose. У ядра нет Docker, у панели тоже.
В v0.107.79 `POST /control/dns_config` принимает поле `disable_ipv6`: `setConfig` пишет его в `AAAADisabled` в ветке без перезапуска DNS-сервера, затем `ConfModifier.Apply` сохраняет конфиг (`internal/dnsforward/http.go`).
В OpenAPI этого тега поля `aaaa_disabled` нет — там оно называется `disable_ipv6`; сверять надо с кодом.
API принимает Basic-авторизацию (`userFromRequestBasicAuth`, `internal/home/authhttp.go`), но пароль владельца у ядра только в bcrypt.
Поэтому ядро держит в `users` своего пользователя `vibedpn-core` с bcrypt пароля из `secrets/adguard-core-password`; хеш переписывается, только когда пароль перестал совпадать, иначе каждый старт ядра менял бы файл новой солью.
AdGuard не ответил — роутер уже применён, ответ `adguard: pending`: файл с тем же значением ядро пишет при своём старте.
Живая смена режима рвёт соединения DoH, которые AdGuard открыл по старому пути, — разбор и решение в разделе «Смена пути DoH на лету» ниже.
**Источники:** https://github.com/AdguardTeam/AdGuardHome/blob/v0.107.79/internal/dnsforward/http.go ,
https://github.com/AdguardTeam/AdGuardHome/blob/v0.107.79/internal/home/authhttp.go ,
https://github.com/AdguardTeam/AdGuardHome/blob/v0.107.79/openapi/openapi.yaml .

## [замер] Смена пути DoH на лету: закрыть соединения, а не перезапускать DNS-сервер

**Контекст:** пункт Stage 13 «сброс соединений DoH при смене режима», стенд `tests/e2e/router.sh`, 2026-09-24.
**Суть:** в `full` пакеты AdGuard (UID 7753) метит цепочка `dns_uplink`, и его соединения DoH идут через выход.
После смены выхода (`full` ↔ `off` или `smart`, смена `default_upstream` в `full`) пакеты тех же соединений уходят другим путём с другим адресом, и сервер отвечает на первый сбросом.
Все запросы, которые в этот момент ждут ответа по такому соединению, получают SERVFAIL за миллисекунды; новое соединение AdGuard открывает на следующем запросе.
В тишине мёртвое соединение ждёт следующего запроса, и он тоже получает SERVFAIL — это и видел стенд.
«Без ответа, через 2 с» в прежней записи — это SERVFAIL: проверка печатала только число ответов, а 2 с — шаг её повторов.

**Факты исходника AdGuard v0.107.79** (`internal/dnsforward/http.go`, `dnsforward.go`):
Любое переданное поле `upstream_dns` перезапускает DNS-сервер, даже с прежним значением: `setIfNotNil` в `setConfigRestartable` сообщает «задано», а не «изменилось».
`Reconfigure` останавливает сервер, ждёт 100 мс, собирает новый прокси (`proxy.New`, кеш пустой) и запускает снова; ответ на запрос API уходит после перезапуска.

**Замер** (зонд в сети устройства спрашивает имена `<метка>.10.0.0.1.nip.io`, которых нет ни в одном кеше; по 6 переключений `full` ↔ `off`):

| Под нагрузкой, 10 запросов/с | как было | перезапуск DNS-сервера | закрыть соединения |
|---|---|---|---|
| Упало запросов | 2–3 | 7–15 | 2–3 |
| Из них без ответа вовсе | 0 | 5–8 | 0 |
| Сбой длится после начала переключения | ≤ 0,08 с | 0,52–1,24 с | ≤ 0,12 с |
| Кеш | сохранён | сброшен: `google.com` 181–774 мс | сохранён |

| В тишине: первый запрос через 3 с после переключения | как было | перезапуск DNS-сервера | закрыть соединения |
|---|---|---|---|
| Первый запрос | SERVFAIL за 1–2 мс, 6 из 6 | ответ за 0,82–0,85 с, 5 из 6 | ответ за 0,63–0,72 с, 6 из 6 |

Перезапуск теряет запросы, которые ждали новое соединение, и после первого перезапуска на стенде новый апстрим 0,9 с стучался в `0.0.0.0:443` (`connection refused`).
Запросы в пути в момент смены падают при любом способе: их соединение умирает раньше, чем кто-то успевает его заменить.

**Решение:** ядро после смены роутера закрывает соединения AdGuard, адресат которых метит `dns_uplink`: IPv4 вне LAN и не на самой коробке, IPv6 — любые, кроме loopback (в `full` IPv6 AdGuard отбрасывается молча, соединение зависло бы, а не сбросилось).
Закрывает через `SOCK_DESTROY` (`engine/sockdiag.py`, разбор ядра — `linux/sockDestroy.md`); в журнал ядра — `AdGuard upstream connections closed: N, their path changed`.
Апстримы по-прежнему уходят только при входе в `smart` и выходе из него: там меняется сам список апстримов.
Без `CONFIG_INET_DIAG_DESTROY` (ядра Raspberry Pi) ядро пишет `AdGuard keeps its upstream connections (…)`, и поведение остаётся прежним.
Тот же путь меняет и `routing.failopen: true`: молчащий шлюз уводит запросы AdGuard напрямую, ответивший — обратно в выход; ядро закрывает соединения и тогда — по событию сторожа выхода в журнале (2026-09-25). При `failopen: false` путь не меняется: молчащий шлюз останавливает запросы, а вернувшийся несёт их тем же путём.
`vibedpn doctor` на коробке с AdGuard спрашивает ядро, умеет ли оно закрывать сокеты, и пишет `dns reconnect` — ok или warn.
**Как применять:** стенд `router.sh` после `mode off`, `mode full`, `upstream wg-stand` и `upstream vps` требует ответа на новое имя с первого запроса и строки ядра о закрытии; «пусто в `full`» для AAAA проверяется кодом ответа NOERROR, а не числом записей.
**Источники:** https://github.com/AdguardTeam/AdGuardHome/blob/v0.107.79/internal/dnsforward/http.go ,
https://github.com/AdguardTeam/AdGuardHome/blob/v0.107.79/internal/dnsforward/dnsforward.go .
