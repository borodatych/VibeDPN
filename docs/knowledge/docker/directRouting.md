# Docker: транзит в bridge-сеть и `nat-unprotected`

## [архитектура] Транзитный трафик LAN в gateway-контейнер режет цепочка DOCKER, а не «direct routing»

**Контекст:** схема роутера (§3.1 idea.md): хост маркирует пакеты LAN и направляет их на
10.77.0.10 / 10.77.0.20 в bridge-сети `vibedpn-upstreams`. Первая версия compose.yaml ставила на
сеть `trusted_host_interfaces=<LAN>`, считая, что это и есть разрешение. Ревью Stage 0 опровергло
это по исходникам moby и живой репродукцией на colima (Engine 29.5.2).
**Суть:** у Docker два разных фильтра. (1) Raw-PREROUTING «direct access»: пакет, адресованный
**на IP контейнера**, принимается только с интерфейсов из `trusted_host_interfaces` и только на
опубликованные порты (`labels.go`: «allowed direct access to published ports on a container's
address»; `iptabler/endpoint.go`: правила `-d <IP контейнера> -i <iface> ACCEPT` / `! -i <bridge>
DROP`). (2) Filter-цепочка `DOCKER`: `! -i <bridge> -o <bridge> -j DROP` для всего, что входит в
бридж не с бриджа (`iptabler/network.go`, `setDefaultForwardRule`), и ACCEPT вместо DROP только в
режиме `gateway_mode_ipv4=nat-unprotected`. Транзитный пакет устройства LAN (dst — адрес в
интернете, next-hop 10.77.0.10) на контейнер не адресован и опубликованных портов не касается —
его убивает фильтр (2), на который `trusted_host_interfaces` не влияет. Репродукция: LAN-netns →
`ip rule` → бридж: с `trusted_host_interfaces` счётчик `DROP ! br-… br-…` растёт, пакеты не
доходят; с `nat-unprotected` — `ACCEPT`, `rx_packets` контейнера растёт. Режимы
`gateway_mode_ipv4`: `nat` (по умолчанию), `nat-unprotected` (Engine ≥ 28.0.0), `routed` (без
NAT, фильтр портов остаётся — транзит всё равно режется), `isolated`. `trusted_host_interfaces`
появился в 28.2.0 и решает другую задачу — доступ из LAN к опубликованным портам по IP контейнера.
Обход `accept`-правилом из собственной nft-таблицы не работает: в nftables `accept` завершает
только свою базовую цепочку, DROP в цепочке Docker сработает всё равно (документация Docker про
nftables-бэкенд говорит то же). Побочно: до 28.0.0 хосты в том же L2 могли достучаться до портов,
опубликованных на localhost, — `127.0.0.1:4449/4050` безопасны только на Engine ≥ 28.
**Применение:** сеть `vibedpn-upstreams` объявляет `gateway_mode_ipv4: nat-unprotected`. Плата —
Docker больше не фильтрует порты контейнеров этой сети (10.77.0.20:4050 TequilAPI станет виден из
LAN, как только Stage 4 включит транзит), поэтому router-engine обязан в forward-хуке дропать
трафик LAN с `ip daddr 10.77.0.0/24` и пропускать только транзит (`drop` в своей таблице работает,
в отличие от `accept`) — пункт Stage 4 в roadmap. `doctor` проверяет Engine ≥ 28.0.0. На Linux-хосте
проверка: `iptables -S DOCKER` показывает `! -i br-… -o br-… -j ACCEPT` для сети шлюзов.
**Источники:** https://docs.docker.com/engine/network/port-publishing/ (gateway modes, direct
routing, trusted host interfaces), https://docs.docker.com/engine/network/drivers/bridge/ ,
https://docs.docker.com/engine/network/firewall-nftables/ (accept не финален),
https://github.com/moby/moby/blob/master/daemon/libnetwork/drivers/bridge/labels.go ,
https://github.com/moby/moby/blob/master/daemon/libnetwork/drivers/bridge/internal/iptabler/network.go ,
https://github.com/moby/moby/blob/master/daemon/libnetwork/drivers/bridge/internal/iptabler/endpoint.go ,
https://docs.docker.com/engine/release-notes/28/ (28.0.0 nat-unprotected, 28.2.0 trusted_host_interfaces).
