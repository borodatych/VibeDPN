# Закрыть чужое TCP-соединение из ядра VibeDPN: `SOCK_DESTROY`

**Контекст:** смена пути DoH AdGuard на лету (knowledge `adguard/docker.md`), `core/vibedpn/engine/sockdiag.py`, 2026-09-24.

## [факт] Что умеет netlink `sock_diag` и чего он требует

Семейство `NETLINK_SOCK_DIAG` (4) по запросу `SOCK_DIAG_BY_FAMILY` (20) с `NLM_F_DUMP` отдаёт все TCP-сокеты семейства: адреса, порты, UID владельца, inode и cookie.
Запрос `SOCK_DESTROY` (21) с тем же идентификатором сокета, cookie включительно, закрывает ровно его — так работает `ss -K`.
Раскладка: `inet_diag_req_v2` — 8 байт и 48 байт `inet_diag_sockid` (порты и адреса в сетевом порядке, интерфейс и cookie — в порядке хоста), ответ `inet_diag_msg` — 72 байта, UID на смещении 64.
`sock_diag_destroy` требует `CAP_NET_ADMIN` в сетевом пространстве сокета (иначе `EPERM`) и обработчик `diag_destroy` у протокола (иначе `EOPNOTSUPP`).
Для TCP обработчик есть, только если ядро собрано с `CONFIG_INET_DIAG_DESTROY`, а по умолчанию эта опция выключена (`default n`).
Ядра Debian bookworm и latest собраны с ней (`CONFIG_INET_DIAG_DESTROY=y`), конфигурации Raspberry Pi `bcm2711_defconfig` и `bcm2712_defconfig` ветки `rpi-6.12.y` — без неё.
Ядро стенда colima (Ubuntu 24.04, 6.8.0-117) — с ней.
Проверено исполнением в контейнере ядра на хосте colima: `list_connections()` нашёл живое соединение `127.0.0.1:53512 → 127.0.0.1:39209` с верным UID, `close_where` закрыл его, клиентский сокет на следующей записи получил `ECONNABORTED` (103), в списке соединения не осталось.
**Как применять:** закрытое так соединение его владелец видит ошибкой на следующем вызове и открывает новое — то, что нужно, когда путь соединения сменился под ним.
Ядро без опции — не повод отказываться от механизма: `EOPNOTSUPP` ловится, пишется в журнал, остальное работает как без него.
**Источники:** https://raw.githubusercontent.com/torvalds/linux/master/include/uapi/linux/inet_diag.h ,
https://raw.githubusercontent.com/torvalds/linux/master/include/uapi/linux/sock_diag.h ,
https://raw.githubusercontent.com/torvalds/linux/master/net/core/sock_diag.c ,
https://raw.githubusercontent.com/torvalds/linux/master/net/ipv4/tcp_diag.c ,
https://raw.githubusercontent.com/torvalds/linux/master/net/ipv4/Kconfig ,
https://salsa.debian.org/kernel-team/linux/-/raw/debian/6.1/bookworm/debian/config/config ,
https://raw.githubusercontent.com/raspberrypi/linux/rpi-6.12.y/arch/arm64/configs/bcm2711_defconfig .
