# iproute2: JSON-вывод для детекта

## [провайдер] `ip -j` как источник фактов о сети

**Контекст:** `vibedpn init` определяет интерфейс с маршрутом по умолчанию, его адрес и подсеть.
**Суть:** `ip -j -4 route show default` отдаёт список объектов `{"dst": "default", "gateway": …,
"dev": "eth0", "flags": []}`; `ip -j -4 addr show dev eth0` — `[{"ifname": "eth0", "addr_info":
[{"family": "inet", "local": "172.17.0.2", "prefixlen": 16, "scope": "global", …}]}]`; у
loopback `scope: "host"`. Снято с iproute2 в `debian:trixie-slim` (2026-09-12), лежит фикстурами в
`core/tests/fixtures/`, парсеры на них и тестируются. В минимальных образах `iproute2` нет —
`install.sh` ставит его явно. Проверка модуля: `/sys/module/wireguard` (загружен) либо
`modprobe -n -q wireguard` (доступен, код 0). `ipaddress.is_global` считает не глобальными не
только RFC 1918, но и CGNAT 100.64/10 и документационные сети 203.0.113/24 — в тестах для
«публичного» адреса брать реальный глобальный.
**Источники:** https://man7.org/linux/man-pages/man8/ip.8.html (флаг `-j`), фикстуры в репозитории,
https://docs.python.org/3/library/ipaddress.html#ipaddress.IPv4Address.is_global .
