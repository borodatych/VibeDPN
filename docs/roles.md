# Роли коробки

Роль — это пресет профилей Docker Compose: один `compose.yaml`, `vibedpn init --role X`
выставляет `COMPOSE_PROFILES` в `.env` и пишет `config.yaml`. Что обязательно и что запрещено в
конфиге каждой роли — [manuals/configSpec.md](manuals/configSpec.md).

| Роль | Где стоит | Что запущено | Кому |
|---|---|---|---|
| `home` | дома, одна коробка | provider + consumer + router + dns + ui | «хочу всё в одной коробке» |
| `vps` | VPS | provider + wg-server + api (headless) | нода отдельно, дома клиент |
| `client` | дома | consumer + wg-client + router + dns + ui | вторая половина связки с `vps` |

## Профили и контейнеры

| Профиль | Контейнер | Сеть | Роли |
|---|---|---|---|
| всегда | `core` (FastAPI + router-engine + CLI-бэкенд) | host, `NET_ADMIN` | все |
| `provider` | `myst-provider` | bridge, published UDP-диапазоны | `home`, `vps` |
| `consumer` | `myst-consumer` (аплинк `dpn`) | `vibedpn-upstreams` 10.77.0.20 | `home`, `client` |
| `wg-server` | `wg-server` | host, 51820/udp | `vps` |
| `wg-client` | `wg-client` (аплинк `vps`) | `vibedpn-upstreams` 10.77.0.10 | `client` |
| `router` | помощники LAN-стороны: dnsmasq для gateway-режима (Stage 9) и smart-режима (Stage 10) | host | `home`, `client` |
| `dns` | `adguard` | host, 53 на LAN-интерфейсе | `home`, `client` |
| `ui` | `ui` (nginx + статика) | host, порт на LAN-интерфейсе | `home`, `client` |

## Связка `vps` + `client`

У VPS два аплинка наружу: публичная myst-нода (зарабатывает) и приватный WireGuard-сервер для
своих домашних коробок (бесплатный быстрый туннель). Один VPS обслуживает несколько домашних
клиентов: `vibedpn peer add <name>` на VPS выдаёт `<name>.conf`, дома —
`vibedpn init --role client --peer-config <name>.conf` кладёт его в `secrets/wg-client.conf`,
откуда его читает контейнер `wg-client`. Через этот же туннель VPS отдаёт домой
свою панель ноды и API `core` — наружу они не торчат. Трафик домашних коробок в интернет VPS
выпускает под своим адресом: `core` при старте грузит таблицу `inet vibedpn_egress` (masquerade
подсети туннеля) и правила в цепочке `DOCKER-USER`, которые пропускают пересылку мимо политики
DROP, выставленной Docker.

## Главный принцип: каждый аплинк — gateway-контейнер

Ни один туннель не живёт в сетевом пространстве хоста. `core` только маркирует трафик LAN и
направляет его в нужный контейнер-шлюз (метка → `ip rule` → таблица аплинка с маршрутом через
`vibedpn0`, мост сети `vibedpn-upstreams`); default route хоста он не трогает никогда. Пока шлюз не
отвечает на проверку, маршрута на него нет: трафик стоит или идёт напрямую по `routing.failopen`. Новый бэкенд —
это ещё один gateway-контейнер и id аплинка, ядро роутера не меняется.
