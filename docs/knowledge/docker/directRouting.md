# Docker Engine ≥ 28: прямой доступ к IP контейнеров закрыт

## [архитектура] Трафик LAN до gateway-контейнера — это «direct routing», и по умолчанию он режется

**Контекст:** вся схема роутера (§3.1 idea.md): хост маркирует пакеты LAN и шлёт их на
10.77.0.10 / 10.77.0.20 в bridge-сети `vibedpn-upstreams`. Критик исследования Stage 0 указал,
что Docker с версии 28 такой трафик по умолчанию не пропускает; проверено по документации.
**Суть:** «By default, remote hosts are not allowed direct access to container IP addresses in
Docker's Linux bridge networks.» Пакет с устройства LAN, пришедший через интерфейс хоста и
направленный на адрес контейнера, — именно этот случай. Разрешить можно тремя способами:
глобально `"allow-direct-routing": true` в `daemon.json` (слишком широко), режимом сети
`com.docker.network.bridge.gateway_mode_ipv4=nat-unprotected` (снимает фильтрацию портов
целиком) или точечно — опцией сети `com.docker.network.bridge.trusted_host_interfaces=<iface>`:
прямой доступ только через перечисленные интерфейсы хоста. Режимы: `nat` (по умолчанию: NAT и
masquerade для опубликованных портов), `nat-unprotected`, `routed` (без NAT, но фильтр
опубликованных портов остаётся; исходящие пакеты идут с адреса контейнера), `isolated` (только с
`--internal`). Побочный факт: до 28.0.0 хосты в том же L2-сегменте могли достучаться до портов,
опубликованных на localhost, — наши `127.0.0.1:4449`/`4050` безопасны только на Engine ≥ 28.
**Применение:** сеть `vibedpn-upstreams` в compose.yaml объявляет
`driver_opts: com.docker.network.bridge.trusted_host_interfaces: ${VIBEDPN_LAN_IFACE}`, значение
пишет `init` из `network.lan_interface`. Опции сети нельзя поменять без её пересоздания —
`vibedpn init` при смене интерфейса обязан пересоздать сеть (Stage 1/4). `doctor` проверяет
версию Engine ≥ 28 (Stage 1).
**Источники:** https://docs.docker.com/engine/network/port-publishing/ (разделы про gateway
modes, direct routing, trusted host interfaces), https://docs.docker.com/engine/network/drivers/bridge/
(опции драйвера, `gateway_mode_ipv4` default `nat`),
https://docs.docker.com/engine/network/packet-filtering-firewalls/ .
