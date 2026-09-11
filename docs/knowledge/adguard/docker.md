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
**Источники:** https://hub.docker.com/r/adguard/adguardhome ,
https://raw.githubusercontent.com/AdguardTeam/AdGuardHome/v0.107.79/docker/build.Dockerfile ,
https://raw.githubusercontent.com/AdguardTeam/AdGuardHome/v0.107.79/internal/home/home.go ,
https://raw.githubusercontent.com/AdguardTeam/AdGuardHome/v0.107.79/internal/configmigrate/configmigrate.go ,
https://adguard-dns.io/kb/adguard-home/configuration/ , https://adguard-dns.io/kb/adguard-home/faq/ ,
https://github.com/AdguardTeam/AdGuardHome/releases/latest .
