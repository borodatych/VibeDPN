# Sentinel dVPN: разведка второго DPN-бэкенда

**Контекст:** Stage 13, «второй DPN-бэкенд Sentinel», 2026-09-25. Всё проверено с домашней коробки (Ростелеком) или по исходникам клиента.

## [факт] Что такое клиент и как он платит

Sentinel — dVPN на своей цепочке Cosmos, `sentinelhub-2`; токен — P2P, в цепочке `udvpn` (миллионная доля).
Клиент — `sentinel-dvpncli` (Go), у репозитория свой `Dockerfile` и публикация образа в `ghcr.io` (`.github/workflows/docker-publish.yml`); в образе `wireguard-tools`, `v2ray`, `xray`, `openvpn`, `hysteria2` и AmneziaWG (`awg`, `amneziawg-go`).
Подключение — две команды: `tx session-start <адрес узла> --denom udvpn --gigabytes N` (или `--hours N`) и `connect <id сессии>`; ключ кошелька — `keys` клиента.
Платится узлу за гигабайт или за час из баланса кошелька; тарифы узел объявляет сам в нескольких токенах.
Цены (1 733 активных узла, 2026-09-25): медиана 40 P2P за ГБ, от 0.0001 до 1 053; P2P по CoinGecko — $0.0000758, то есть медиана около $0.003 за ГБ (поле `base_value` тарифа, медиана 0.0025, сходится).
**Источники:** https://docs.sentinel.co/dvpn-cli/get-started , https://github.com/sentinel-official/sentinel-dvpncli (коммит 4b0f856, `Dockerfile`, `tx/session.go`, `service/connect.go`), https://docs.sentinel.co/networks/endpoints , https://api.coingecko.com/api/v3/simple/price?ids=sentinel&vs_currencies=usd .

## [замер] Проходит ли сеть у провайдера

Публичные REST цепочки с коробки: `lcd.sentinel.co` отвечает 307 от Cloudflare даже на запрос API, `sentinel-api.polkachu.com` и `sentinel-rest.publicnode.com` — 200; список узлов — `GET /sentinel/node/v3/nodes?status=1` (`v2` отвечает «unknown service»).
TCP и TLS до API случайных 150 из 1 733 узлов: рукопожатие TLS у 123 (82%), таймаут TCP у 25, отказ у 2; без контрольной точки вне России таймауты не отличить от выключенных узлов.
Типы 117 ответивших узлов (`GET /` узла): `wireguard` 61, `v2ray` 54, `hysteria2` 1, `amneziawg` 1; страны — США 46, Великобритания 8, Япония 7, Германия 6.
Сам туннель не проверен: нужна сессия, а её оплата — токены на кошельке владельца.
Для этой линии важно: рукопожатие WireGuard к Proton здесь не проходит (замер, knowledge `wireguard/protonFree.md`), так что с узлами `wireguard` может быть так же; бэкенд должен уметь выбирать узлы `v2ray` (TCP, TLS/WebSocket), а AmneziaWG пока редкость.
**Как применять:** узел выбирать по типу и стране из `v3/nodes` и `GET /` узла, а не наугад; REST брать не только `lcd.sentinel.co`.

## [решение] Чего ждёт следующий шаг

Встраивание по образцу `dpn`: шлюз-контейнер из официального образа клиента, ключ кошелька — секрет, сессия на выбранный узел, kill switch как у остальных выходов.
Перед кодом — живая проверка туннеля `v2ray` и `wireguard` с домашней линии, для неё нужен кошелёк с P2P: покупку делает владелец.
