# nftables для файрвола VPS

## [провайдер] Что проверено исполнением (nftables 1.1.3, trixie, контейнер с NET_ADMIN)

**Суть:** `add table inet vibedpn` + `delete table inet vibedpn` + описание таблицы в одном файле
— атомарная и идемпотентная замена: второй `nft -f` даёт тот же ruleset, изменённый — ровно
новый. **Не `flush table`:** он удаляет цепочки и правила, но элементы set переживают его, и
`elements = { 56000-56050 }` поверх старых `{ 56000-56100 }` даёт «Could not process rule: File
exists» (EEXIST от ядра, `nft -c` тоже) — core уходил бы в рестарт-цикл при любой правке
`provider.udp_ports` с пересечением, а непересекающийся диапазон молча добавлялся к старому
(проверено nftables 1.1.3 в контейнере с NET_ADMIN: после `delete table` в наборе только новый
диапазон, CI это повторяет). `nft -c -f -`
(проверка синтаксиса) тоже требует `NET_ADMIN`: без него «cache initialization failed:
Operation not permitted» — поэтому синтаксис нельзя проверить в юнит-тестах, только в контейнере
с capability (задача CI `firewall`). Набор портов: `set myst_udp { type inet_service; flags
interval; elements = { 56000-56100 } }`, использование `udp dport @myst_udp`. Списки портов
inline: `tcp dport { 22, 2222 } accept`. `nft -j list tables` отдаёт JSON
`{"nftables": [{"metainfo": …}, {"table": {"family": "inet", "name": "vibedpn", …}}]}` — так
`doctor` узнаёт, загружена ли таблица. Опубликованные порты контейнеров (UDP ноды в bridge-сети)
идут через prerouting DNAT и FORWARD, а не через нашу цепочку input, — правило `udp dport
@myst_udp` в input нужно только для ноды в host-сети, но безвредно. `nft`, как и `modprobe`,
живёт в sbin — искать явно. sshd: «for each keyword, the first obtained value will be used»,
но `Port` — исключение: несколько директив разрешены и sshd слушает все, `Include` обрабатывается
в лексическом порядке относительно `/etc/ssh` — поэтому в конфиге `ssh_ports` список, а `init`
собирает все `Port` вне `Match`-блоков.
**Источники:** исполнение 2026-09-12; https://wiki.nftables.org/wiki-nftables/index.php/Sets ,
https://wiki.nftables.org/wiki-nftables/index.php/Atomic_rule_replacement ,
https://man.openbsd.org/sshd_config (Port, Include).

## [баг] Порты sshd: токенизация как у sshd, `ListenAddress host:port`, `sshd -T`

**Контекст:** ревью nftables-baseline (2026-09-12): `init` резал строку `sshd_config` одним
`partition(" ")`.
**Суть:** sshd делит строку директивы по любому пробельному символу или ровно одному `=`
(`misc.c`, `strdelim`: `strpbrk(s, WHITESPACE QUOTE "=")`), значения могут быть в двойных
кавычках — `Port\t2222`, `Port=2222`, `Port "2222"`, `Match\tUser` и `Include\t…` парсер по пробелу
не видел и молча отдавал `[22]`; на VPS с sshd на 2222 это `policy drop` без ssh. Порт задаётся и в
`ListenAddress`: с портом (`host:port`, `[v6]:port`, хвост `rdomain N`) sshd слушает именно его, без
порта — все `Port`; нет `ListenAddress` — все `Port` на всех адресах. Проверено `sshd -T -f cfg`
(OpenSSH 9.6): `Port 22 + Port 2222` → `port 22`, `port 2222`, по строке `listenaddress` на каждый
порт и семейство (`[::]:22`, `0.0.0.0:22`, …); `ListenAddress 0.0.0.0:2200 + Port 22` → одна
`listenaddress 0.0.0.0:2200`, 22 не слушается. Самый надёжный источник — `sshd -T`: печатает
нормализованный конфиг (строчные ключи, один пробел, `Include` и `=` уже разрешены), но требует
root (без хост-ключей: «no hostkeys available -- exiting»), поэтому `init` под sudo сначала
спрашивает его, файловый парсер — запасной путь. `sshd -T` не знает про socket-активацию
(`ssh.socket` Ubuntu: порт в `ListenStream`, `Port` в конфиге игнорируется) — это ловит `doctor`,
сверяя `ss -lntp` (процесс `sshd`) с `firewall.ssh_ports`.
**Применение:** `detect.sshd_directives` / `parse_sshd_ports` / `sshd_effective_ports`,
`doctor._ssh_result`.
**Источники:** https://raw.githubusercontent.com/openssh/openssh-portable/master/misc.c (strdelim),
https://man.openbsd.org/sshd_config (Port, ListenAddress, Include), https://man.openbsd.org/sshd (-T);
исполнение 2026-09-12 (`sshd -T -f`, OpenSSH 9.6 в colima).

## [баг] DHCPv6 не проходит как established; снятие таблицы — `add table` + `delete table`

**Суть:** запрос DHCPv6 клиент шлёт с link-local на multicast `ff02::1:2`, ответ приходит unicast
с link-local сервера или релея — conntrack не связывает его с запросом, и при `policy drop` с одним
`ct state established,related accept` VPS с адресом по DHCPv6 теряет IPv6 при продлении аренды.
Правило как у ufw (`before6.rules`: `-p udp -s fe80::/10 --sport 547 -d fe80::/10 --dport 546
ACCEPT`): `ip6 saddr fe80::/10 ip6 daddr fe80::/10 udp sport 547 udp dport 546 accept`. Снятие
таблицы одной транзакцией `add table inet vibedpn` + `delete table inet vibedpn`: `delete`
несуществующей таблицы — ошибка, `add` существующей — no-op, поэтому пара идемпотентна;
`nft -c` на пустом ядре её принимает. Проверено nftables 1.1.3 в контейнере с NET_ADMIN:
правило DHCPv6 применяется дважды без ошибок, teardown дважды — таблицы нет. `core` снимает
таблицу при старте, когда в конфиге файрвола нет (`enabled: false`, роль без файрвола);
`vibedpn down` её не трогает — намеренно: погашенная VPS остаётся закрытой, ssh и `allow_*`
открыты по последним правилам.
**Источники:** https://git.launchpad.net/ufw/plain/conf/before6.rules (строка с 546/547),
https://www.rfc-editor.org/rfc/rfc8415#section-16 (клиент шлёт с link-local),
https://wiki.nftables.org/wiki-nftables/index.php/Configuring_tables (add/delete table);
исполнение 2026-09-12.

## [провайдер] `add element` не продлевает таймаут существующего элемента

**Контекст:** Stage 10, резолвер ядра кладёт адреса доменов в наборы `smart_*` с таймаутом и продлевает его при каждом ответе, 2026-09-14.

**Суть (исполнением, nftables 1.1.6 в Alpine 3.24, набор `type ipv4_addr; flags timeout`, colima VM):**
`add element … { 198.51.100.7 timeout 30s }`, затем `add element … { 198.51.100.7 timeout 600s }` — код 0, но элемент остаётся `timeout 30s expires 29s…`.
`create element` на существующем — `Error: Could not process rule: File exists`.
`delete element` и отдельный `add element` дают `timeout 10m`, но между командами адреса в наборе нет.
Одна транзакция `nft -f -` из трёх строк — `add element … { a timeout T, b timeout T }`, `delete element … { a, b }`, `add element … { a timeout T, b timeout T }` — код 0: существующий `a` получил `timeout 10m`, новый `b` создан с тем же таймаутом.
Транзакция применяется целиком или не применяется, поэтому адрес не выпадает из набора.


## Длина имени набора: «16 символов» — старое ограничение

Поиск по «nftables set name maximum length» выдаёт «не длиннее 16 символов» — это из документации времён RHEL 7 (старые ядра).
Проверено на коробке 2026-09-16 (ядро `7.1.8+deb13-amd64`, `nftables v1.1.3`): в одноразовой таблице `inet vdpn_probe` созданы наборы `smart_wg_proton` (15 символов), `smart_wg_abcdefghijklmnopqrstuvwx` (33) и имя из 55 символов с подчёркиваниями — все приняты, таблица удалена.
Коробка поддерживает ядра не старше Debian 12 (6.1), поэтому имена наборов `smart_wg_<имя выхода>` до 33 символов безопасны.
Дефис в имени выхода коробка заменяет на `_`: имя выхода само подчёркиваний не содержит, так что два выхода одного набора не делят.
