# dnsmasq и nftset: в какой сборке он есть

## [провайдер] Alpine 3.24 собирает dnsmasq без nftset

**Контекст:** Stage 10, smart-режим — адреса доменов из списков должны попадать в nft-набор роутера `inet vibedpn_router`, 2026-09-13.

**Суть (исполнением, образ `images/dnsmasq` на `alpine:3.24`):**
`dnsmasq --version` — `Dnsmasq version 2.92rel2`, строка опций сборки:
`IPv6 GNU-getopt no-DBus no-UBus no-i18n no-IDN DHCP DHCPv6 no-Lua TFTP no-conntrack ipset no-nftset auth no-DNSSEC loop-detect inotify dumpfile`.
В `dnsmasq --help` опция при этом описана: `--nftset=/<domain>[/<domain>...]/<nftset>...` — справка не говорит, вошла ли она в сборку, это видно только по `no-nftset` в `--version`.
`ipset` в сборке есть, но это наборы старого `ip_set` ядра, а роутер коробки держит свои наборы в nftables.

## [провайдер] Debian trixie собирает dnsmasq с nftset

**Суть (исполнением, `debian:trixie-slim` 13.6, пакет `dnsmasq-base` 2.91-1+deb13u2, установлено 1153 КБ):**
`Compile time options: IPv6 GNU-getopt DBus no-UBus i18n IDN2 DHCP DHCPv6 no-Lua TFTP conntrack ipset nftset auth DNSSEC loop-detect inotify dumpfile`.

## [провайдер] nftset в набор таблицы inet: синтаксис, таймаут, поддомены

**Суть (исполнением, dnsmasq 2.91 Debian trixie, nftables 1.1.3, контейнер с `NET_ADMIN` в сети хоста, 2026-09-13):**
Набор `set smart4 { type ipv4_addr; flags timeout; timeout 1h; }` в `table inet vibedpn_lab`.
dnsmasq с `--nftset=/example.com/4#inet#vibedpn_lab#smart4` на запрос `www.example.com` добавил оба адреса ответа: `elements = { 104.20.23.154 expires 59m59s944ms, 172.66.147.243 expires 59m59s941ms }`.
Элемент получает таймаут набора; домен правила покрывает поддомены; ответ на `example.org` в набор не попал.
Журнал: `nftset add 4 inet vibedpn_lab smart4 172.66.147.243 example.com`.
Если таблицы нет, dnsmasq отвечает клиенту как обычно и пишет `nftset inet vibedpn_lab smart4 Error: No such file or directory` — ответ без адреса в наборе, то есть мимо аплинка.

**Грабля опыта:** `docker exec` без `-i` не передаёт stdin: `nft -f -` молча ничего не загрузил.

**Как применять:** smart-режиму нужен dnsmasq, у которого в `--version` стоит `nftset`, а не `no-nftset`; пакет Alpine для этого не подходит, пакет Debian trixie — подходит; DHCP-образу gateway-режима nftset не нужен.

**Источники:** https://thekelleys.org.uk/dnsmasq/docs/dnsmasq-man.html (опция `--nftset`; наличие в сборке снято исполнением).
