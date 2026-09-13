# AdGuard Home за пересылающим DNS: клиент теряется

## [провайдер] За dnsmasq все запросы записаны от адреса dnsmasq

**Контекст:** Stage 10, smart-режим; в `docs/idea.md` записано «dnsmasq с `nftset=` перед AdGuard», 2026-09-13.

**Суть (исполнением, `adguard/adguardhome:v0.107.79` и dnsmasq 2.91 Debian trixie, оба в сети хоста colima VM):**
AdGuard на `127.0.0.1:5300` с конфигом из фикстуры `core/tests/fixtures/adguard_v0_107_79.yaml` (в нём `trusted_proxies: [127.0.0.0/8, ::1/128]`).
dnsmasq на `127.0.0.1:5399` с `--server=127.0.0.1#5300 --add-subnet=32 --add-mac`.
Запрос `example.com` с `127.0.0.7` через dnsmasq — в журнале AdGuard (`GET /control/querylog`) клиент `127.0.0.1`.
Запрос `example.net` с `127.0.0.8` прямо в AdGuard — клиент `127.0.0.8`.
Ни EDNS Client Subnet, ни MAC в EDNS от dnsmasq AdGuard не использует для опознания клиента.

**Из документации:**
`ipset` / `ipset_file` — «adding IP addresses of the specified domain names to an ipset list», только Linux ipset, не наборы nftables.
`trusted_proxies` — только для DNS-over-HTTPS: заголовки `X-Real-IP` и подобные, не обычный DNS.
`edns_client_subnet` добавляет ECS в запросы к апстриму; об опознании клиентов по ECS не сказано.

**Как применять:** dnsmasq перед AdGuard для всех запросов лишает AdGuard журнала и настроек по устройствам; наполнять nft-набор самим AdGuard нельзя.

**Грабля опыта:** рабочий каталог AdGuard после опыта принадлежит root — убирать через `sudo`.

**Источники:** https://github.com/AdguardTeam/AdGuardHome/wiki/Configuration (ключи `ipset`, `trusted_proxies`, `edns_client_subnet`); https://adguard-dns.io/kb/adguard-home/clients/ (способы опознания клиентов — о пересылающих серверах ничего).
