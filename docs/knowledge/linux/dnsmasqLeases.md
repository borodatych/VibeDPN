# Аренды DHCP dnsmasq: формат файла

## [провайдер] Строка аренды — время, MAC, адрес, имя, client-id

**Контекст:** Stage 9, аренды dnsmasq как источник устройств и имён в gateway-режиме, 2026-09-13.
**Суть (исполнением, dnsmasq 2.92 из Alpine 3.24):** dnsmasq только на DHCP (`--port=0`, `--interface`, `--bind-interfaces`, `--dhcp-range`, `--dhcp-option=option:router,...`, `option:dns-server,...`, `--dhcp-leasefile`, `--dhcp-authoritative`) в netns за мостом; клиент `udhcpc -x hostname:lab-phone` получил адрес, файл аренд — одна строка на аренду, пять полей через пробел:
`1789371673 76:39:40:76:15:d0 192.168.99.143 lab-phone 01:76:39:40:76:15:d0` — время истечения (секунды Unix), MAC, IPv4, имя хоста от клиента, client-id.
Журнал dnsmasq пишет ту же аренду как `DHCPACK(dls) 192.168.99.143 76:39:40:76:15:d0 lab-phone`.
**Клиент без имени (исполнением, стенд `tests/e2e/gateway.sh`, `dhcpcd` без hostname, 2026-09-13):** на месте имени `*`, client-id длинный (DUID):
`1789332982 b2:57:6f:bb:ec:c1 192.168.78.114 * ff:6f:bb:ec:c1:00:01:00:01:…` — ядро читает `*` как «имени нет» и берёт PTR.
**Не проверено:** срок `0` у аренды `infinite` — разбор считает такую аренду бессрочной.
**Грабля опыта:** контейнер с `--network none` не ставит пакеты (`apk` — «DNS: transient error»): образ с dnsmasq собирается заранее, с сетью.
**Источники:** https://thekelleys.org.uk/dnsmasq/docs/dnsmasq-man.html (опции `--dhcp-range`, `--dhcp-option`, `--port`, `--bind-interfaces`, `--dhcp-leasefile`, `--dhcp-authoritative`; формат строк там не описан — снят исполнением).
