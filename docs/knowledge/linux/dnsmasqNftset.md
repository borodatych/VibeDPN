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

**Как применять:** smart-режиму нужен dnsmasq, у которого в `--version` стоит `nftset`, а не `no-nftset`; пакет Alpine для этого не подходит, пакет Debian trixie — подходит; DHCP-образу gateway-режима nftset не нужен.

**Источники:** https://thekelleys.org.uk/dnsmasq/docs/dnsmasq-man.html (опция `--nftset`; наличие в сборке снято исполнением).
