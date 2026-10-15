# AmneziaWG: версии, параметры, демон, клиенты

Проверено 2026-10-15. Исходники клонированы в `/Volumes/Storage/Caches/vibedpn/` (amneziawg-go, amneziawg-tools, amneziawg-android).

## [протокол] Какая версия и почему именно она

**Контекст:** WireGuard режут по сигнатуре (ТСПУ, DPI): фиксированные заголовки и размеры пакетов. AmneziaWG — форк WireGuard,
который прячет эти признаки; с выключенными параметрами он совместим с обычным WireGuard.
**Суть:** линейка версий по описанию разработчиков: 1.0 (первые параметры), 1.5 (маскировка под QUIC/DNS и т.п.),
2.0 (диапазоны заголовков вместо одного числа, случайные байты в служебных пакетах, цепочка сигнатурных пакетов I1–I5),
3.0 и 3.1 (защита заголовков, добавка к полезной нагрузке, свои тайминги, случайные хвосты, отключение Cookie Reply).
Версия 3.1 сделана в ответ на массовые блокировки в России в июне–июле 2026. Криптографическое ядро (Noise_IK, Curve25519,
ChaCha20-Poly1305) не менялось.
**Решение для VibeDPN: целимся в AmneziaWG 3.1** — самая сильная версия, которую уже понимают актуальные клиенты (таблица ниже).
Совместимость версий: разбор конфига в приложении 3.1 на неизвестный ключ отвечает ошибкой (`UNKNOWN_ATTRIBUTE` в `Interface.java`
amneziawg-android), и приложение версии 2.0, вероятнее всего, так же отвергнет ключи 3.x — **не проверено на 2.0-клиенте**.
Демон 3.1 принимает набор ключей 2.0 как есть (проверено стендом `tests/wg/tunnel.sh`, вариант `awg2`).
**Зафиксировано в образе:** `amneziawg-go v3.1.20260828` (commit `b5928efb6ca19f0153958460c3d141f04abc5c2e`) и
`amneziawg-tools v3.1.20260812` (commit `ee0f0a9aa34ff0a0da4b3433b9512781cfe02843`). Тот же коммит tools подмодулем в
`amneziawg-android`. После `v3.1.20260814` в демоне вышли два исправления (`use udp window for RandomPaddingAddition`,
`disable the whole underload if DisableCookies is on`): приложения собраны на `v3.1.20260814` и их не содержат; формат пакетов
они не меняют (по сообщениям коммитов, сам дифф не сверялся).
**Источники:** https://docs.amnezia.org/en/documentation/amnezia-wg ,
https://github.com/amnezia-vpn/amneziawg-go (README, теги) , https://github.com/amnezia-vpn/amneziawg-tools (теги) .

## [клиенты] Кто понимает 3.1 (по датам выпусков)

**Суть:**
- AmneziaVPN (рабочий стол и Android): 5.0.0.5 (2026-07-26) — «Added AWG 3 support»; 5.0.1.5 (2026-08-21) — «Added AWG 3.1 support»;
  последний на момент проверки 5.0.3.0 (2026-09-18). https://github.com/amnezia-vpn/amnezia-client/releases
- AmneziaWG для Android (отдельное приложение): релиз `v3.1.20260814`; разбор конфига в исходниках знает все ключи 3.1
  (`HeaderProtectionKey`, `ContentPaddingAddition`, `RekeyAfterTime`, …, `RandomTrailers`, `DisableCookies`;
  `tunnel/src/main/java/org/amnezia/awg/config/Interface.java`). https://github.com/amnezia-vpn/amneziawg-android/releases
- AmneziaWG для Windows: `amneziawg-windows-client` 3.1.0 (2026-08-21), «add awg3.1 support».
  https://github.com/amnezia-vpn/amneziawg-windows-client/releases
- AmneziaWG для iOS/macOS: в `amneziawg-apple` есть тег `v3.1.20260814` (коммит от 2026-08-23); **выпуск в App Store не проверен**.
  https://github.com/amnezia-vpn/amneziawg-apple
**Не проверено:** работа конфига 3.1 на реальном устройстве с этими приложениями (на стенде только наш демон с обеих сторон
и ванильный wireguard-go для чистого WireGuard).

## [параметры] Ключи `[Interface]` и границы значений

**Суть** (README amneziawg-go; разбор в amneziawg-tools `src/config.c`; проверка при применении — `device/uapi.go` демона):
- `Jc` — число мусорных пакетов перед рукопожатием, `uint16`, рекомендуют 4–12. `Jmin` ≤ `Jmax`, `uint16`, размер мусорного пакета;
  `Jmax` меньше MTU системы, иначе пакет фрагментируется и выдаёт себя.
- `S1`–`S4` — длины случайных префиксов Init/Response/Cookie/Data, `uint16`. Размеры на проводе: `148+S1`, `92+S2`, `64+S3`,
  `payload+S4`. Для защиты заголовков каждое `Sx` не меньше 12 (`HeaderCipherNonceSize = 12`, `device/noise-types.go`; ошибка
  `S%d must be more then 12 to use headerProtection`).
- `H1`–`H4` — идентификатор типа сообщения Init/Response/Cookie/Data, `uint32`, число или диапазон `a-b`; диапазоны не должны
  пересекаться (ошибка `headers must not overlap`). Значения 1, 2, 3, 4 — стандартные WireGuard: с ними свой заголовок выключен.
  С защитой заголовков документация советует оставлять `H1..H4 = 1..4`.
- `I1`–`I5` — сигнатурные пакеты (CPS), уходят перед рукопожатием по порядку; пустое значение — пакет пропущен. Теги: `<b 0xHEX>`
  (чётная длина hex), `<r N>`, `<rc N>`, `<rd N>` (N ≤ 1000), `<t>` (метка времени, в цепочке один раз). Больше MTU — фрагментация.
  В файле значение допускает пробелы внутри (`<b 0x…><r 16>`): `awg` для ключей `I1`–`I5` ставит пробелы как есть.
- `HeaderProtectionKey` — 32 байта в base64 (как ключ WireGuard, делается `awg genkey`), нужен на обеих сторонах.
- `ContentPaddingAddition` — диапазон `uint16`, случайная добавка к данным не выше внутреннего MTU. README: лучше задать на обеих
  сторонах, но обязательным это не считается.
- `RekeyAfterTime`, `RekeyTimeout`, `RejectAfterTime`, `KeepaliveTimeout`, `MaxHandshakeAttempts` — диапазоны `uint16`, секунды
  (последнее — число попыток); `PersistentKeepalive` пира тоже принимает диапазон. Клиентская сторона.
- `RandomTrailers`, `DisableCookies` — `on`/`off`. Для `RandomTrailers` документация советует одинаковые `S1`–`S4`.
- Значение `0`, `off` или `0-0` выключает механизм. Параметры обязаны совпадать на двух концах: `Jc/Jmin/Jmax`, `I1`–`I5`,
  `ContentPaddingAddition`, тайминги — клиентские (на сервере могут быть иными); `S1`–`S4`, `H1`–`H4`, `HeaderProtectionKey` — общие.
**Как приёмник узнаёт тип пакета** (`device/receive.go`, `DeterminePacketTypeAndPadding`): по размеру (`Sx` + размер сообщения,
при случайных хвостах — не меньше) и по значению заголовка после снятия защиты. Равные `S1`–`S4` рабочие: стенд `awg3`
(`S1=S2=S3=S4=32`) проходит.
**Источники:** https://docs.amnezia.org/en/documentation/amnezia-wg , https://github.com/amnezia-vpn/amneziawg-go ,
https://github.com/amnezia-vpn/amneziawg-tools , https://github.com/amnezia-vpn/amneziawg-android .

## [демон] Userspace-демон: сокет, интерфейс, ограничения

**Суть:** `amneziawg-go [-f] <iface>` создаёт TUN-интерфейс и слушает управляющий сокет `/var/run/amneziawg/<iface>.sock`
(`ipc/uapi_unix.go`: каталог — переменная, пересобирается линкером, по умолчанию `/var/run/amneziawg`; создаётся с правами 0755,
сам сокет 0600). Каталог сокета у `awg` задаётся при сборке (`RUNSTATEDIR`, по умолчанию `/var/run`, путь
`<RUNSTATEDIR>/amneziawg/`). Без `-f` процесс уходит в фон и пишет баннер про ядерный модуль; переменная окружения
`WG_PROCESS_FOREGROUND=1` оставляет его в переднем плане и баннер подавляет — так делает entrypoint (процесс виден
оболочке, умер демон — виден код выхода).
Интерфейс — обычное TUN-устройство: контейнеру нужен `/dev/net/tun` и `NET_ADMIN`, модуль ядра `wireguard` не нужен.
Интерфейс непостоянный: умер процесс — интерфейс исчез (kernel.org, `tuntap`). Остаётся файл сокета; свежий запуск с живым
сокетом отказывает (`unix socket in use`), с мёртвым — убирает его сам.
`awg` на Linux сначала ищет сокет демона с таким именем интерфейса, и только если его нет — идёт к ядерному интерфейсу (netlink):
`ipc_get_device` / `ipc_set_device` в `src/ipc.c`. Поэтому сокет, смонтированный в другой контейнер, достаточен для `awg show`.
**fwmark:** демон ставит метку на свои исходящие пакеты (`SO_MARK`) — kill-switch и policy routing из entrypoint работают
как при ядерном WireGuard (проверено стендом).
**MTU:** демон создаёт интерфейс с 1420, но на проводе каждый транспортный пакет на `S4` байт длиннее: entrypoint, когда в файле
нет `MTU`, берёт `1420 − S4`. `Jmax` и размеры `I1`–`I5` в MTU не входят — это отдельные пакеты.
**Неверное значение:** `awg setconf` на `S1 = abc` печатает ``Unable to parse S1: `abc'`` и завершается кодом 1 — это проверено
исполнением; entrypoint выходит с сообщением про неверную конфигурацию, интерфейс без адресов не остаётся.
**Источники:** https://github.com/amnezia-vpn/amneziawg-go (`main.go`, `ipc/uapi_unix.go`, `device/uapi.go`) ,
https://www.kernel.org/doc/html/latest/networking/tuntap.html .

## [awg] Формат `awg show <if> dump`

**Суть:** табуляции. Первая строка — сам интерфейс **с закрытым ключом и `HeaderProtectionKey`**:
`private-key, public-key, listen-port, Jc, Jmin, Jmax, S1, S2, S3, S4, H1, H2, H3, H4, I1, I2, I3, I4, I5, HeaderProtectionKey,
ContentPaddingAddition, RekeyAfterTime, RekeyTimeout, RejectAfterTime, KeepaliveTimeout, MaxHandshakeAttempts, RandomTrailers,
DisableCookies, fwmark` (`(null)` — пусто, `(none)` — нет ключа, `on`/`off`). Дальше по строке на пира, восемь полей, как у `wg show`:
`public-key, preshared-key, endpoint, allowed-ips, latest-handshake, rx, tx, persistent-keepalive`. Поэтому
`parse_wg_dump` в `core/vibedpn/engine/wg.py` по-прежнему пропускает первую строку целиком и ничего из неё не хранит.
Подкоманды `latest-handshakes`, `allowed-ips`, `persistent-keepalive`, `peers` печатают то же, что `wg`, и есть у `awg`
(как и `set`, `setconf`, `syncconf`, `showconf`, `genkey`, `genpsk`, `pubkey`). Дополнительно: `jc`, `jmin`, `jmax`, `s1`–`s4`, `h1`–`h4`,
`i1`–`i5`, `header-protection-key`, `content-padding-addition`, `rekey-*`, `random-trailers`, `disable-cookies`.
**Проверено исполнением:** образец первой строки снят с живого демона; фикстура `core/tests/fixtures/wg/show_dump.txt` — оттуда.
**Источник:** https://github.com/amnezia-vpn/amneziawg-tools (`src/show.c`, функция `dump_print`).

## [пакеты] Alpine 3.24 не содержит AmneziaWG

**Суть:** `apk search amnezia` в `alpine:3.24` (main и community) и с подключённым edge/testing — пусто; `go` в Alpine 3.24 —
1.26.9, а `amneziawg-go` требует Go 1.25+ (`go.mod`). Поэтому образ `images/wg` собирается из исходников в три этапа:
демон Go кросс-компилируется на машине сборки под нужную архитектуру (`CGO_ENABLED=0`, образ `golang:1.26-alpine3.24`),
`awg` на C собирается на самой целевой архитектуре (`build-base linux-headers`), итог — `alpine:3.24` + `iproute2 nftables`.
Исходники берутся по полному SHA коммита (`ADD https://github.com/…git#<sha>`), тег подменить можно, коммит нельзя.
Размер образа — 27 МБ (arm64). Собрано и запущено на arm64 и amd64.
`core` собирает тот же `awg` на Debian trixie (тот же коммит tools; тест сверяет два Dockerfile), потому что читает состояние
сервера через сокет демона из своего контейнера.
**Источники:** https://pkgs.alpinelinux.org/packages (поиск `amnezia`; пусто — подтверждено `apk search` в контейнере) ,
https://docs.docker.com/reference/dockerfile/ (раздел ADD: git-источник с `#<ref>`, `--keep-git-dir`, `--checksum` — SHA коммита).

## [проверено] Что подтверждает стенд `tests/wg/tunnel.sh`

Три варианта файлов (`plain`, `awg2`, `awg3`) проходят весь сценарий: рукопожатие, трафик, kill-switch, шлюз для LAN с
зажатием MSS, добавление и снятие пира без перезапуска, сервер в сети хоста после краха. В `awg`-вариантах пир без ключей
обфускации за 20 с не завершает рукопожатие ни со своей, ни с серверной стороны. Вариант `plain` дополнительно рукопожимается
с ванильным WireGuard (`wireguard-go` из пакетов Alpine): чистый файл поставщика работает как был.
