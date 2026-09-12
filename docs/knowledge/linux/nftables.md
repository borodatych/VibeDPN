# nftables для файрвола VPS

## [провайдер] Что проверено исполнением (nftables 1.1.3, trixie, контейнер с NET_ADMIN)

**Суть:** `add table inet vibedpn` + `flush table inet vibedpn` + описание таблицы в одном файле
— атомарная и идемпотентная загрузка: второй `nft -f` даёт тот же ruleset. `nft -c -f -`
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
