# Mysterium consumer: ответы на вопросы §10 idea.md

## [провайдер] Flow consumer через TequilAPI в node 1.39.5

**Контекст:** Stage 8, пункт 1 — «обязательно уточнить» из `docs/idea.md` §10; ответы сняты по исходникам тега 1.39.5, 2026-09-13.
**Identity:** `POST /identities` с `{"passphrase": "..."}` — поле обязательно, пустая строка допустима; `PUT /identities/{id}/unlock` с тем же `passphrase`; список — `GET /identities`, одна — `GET /identities/{id}` (статус регистрации, баланс).
**Регистрация:** `POST /identities/{id}/register` (тело необязательно: `fee`, `beneficiary`, `referral_token`). Уже зарегистрирована — 200, в процессе — 422, иначе 202 и транзактор регистрирует в сети. Бесплатно — только если `canRegisterForFree`; право проверяет `GET /transactor/identities/{id}/eligibility` (`{"eligible": bool}`), иначе берётся комиссия транзактора (`GET /transactor/fees`) из баланса.
**Подключение:** `PUT /connection`, обязателен только `consumer_id`; `provider_id` или `filter.country_code` (и `ip_type`, `sort_by`) выбирают предложение, `service_type` по умолчанию `openvpn` (есть `wireguard`). Не зарегистрированная identity — 422 «not registered», регистрация в процессе — соединение идёт дальше. Статус — `GET /connection`, трафик — `GET /connection/statistics`, разрыв — `DELETE /connection`.
**Kill-switch — ловушка имени:** `connect_options.kill_switch` в JSON — это поле `DisableKillSwitch` (`getConnectOptions` передаёт его как есть). `"kill_switch": true` **выключает** kill-switch ноды; чтобы он работал, поле не передаётся или `false`. Для VibeDPN kill-switch держит и сам роутер коробки (маршрут `unreachable` таблицы `dpn`).
**Предложения:** `GET /proposals?country=DE&service_type=wireguard` (ещё `ip_type`, `quality_min`, `nat_compatibility`, `provider_id`); у предложения `location.country`, `price.per_hour_tokens`, `price.per_gib_tokens`, `quality`.
**Оплата и баланс:** перед соединением `Validator` требует разблокированную identity и, если у предложения цена за час или за ГиБ больше нуля, баланс не меньше цены минуты и цены МиБ. При нулевой цене баланс не проверяется.
**Бесплатно через свою ноду:** цену ставит provider флагами `payment.price-gib` (по умолчанию 0.1) и `payment.price-hour` (0.00006). Нулевая цена действует для всех потребителей сети, а не только для своего consumer, — «бесплатный выход через свою ноду» значит раздавать ноду бесплатно всем. Запрета соединяться со своей нодой в менеджере соединений не нашлось, но и явной поддержки тоже — **не проверено**.
**Контейнер без `--net host`:** официальная Docker-инструкция даёт только `--cap-add NET_ADMIN` и том `/var/lib/mysterium-node` и ничего не говорит о consumer, `/dev/net/tun` и host-сети. Compose коробки даёт consumer `NET_ADMIN`, `/dev/net/tun` и `ip_forward=1` — проверяется запуском в пункте «gateway-контейнер».
**Образ:** `mysteriumnetwork/myst:1.39.5-alpine` — официальный мультиарх-манифест amd64, arm (v7), arm64 (`docker manifest inspect`), свой образ не нужен.
**Каталоги и обновление:** каталог данных — флаг `--data-dir` (`config/flags_directory.go`), в образе `/var/lib/mysterium-node`. Флагов автообновления в `config/flags_*.go` тега нет: версию задаёт тег образа.
**Источники:** https://github.com/mysteriumnetwork/node/blob/1.39.5/tequilapi/endpoints/identities.go ,
https://github.com/mysteriumnetwork/node/blob/1.39.5/tequilapi/contract/identity.go ,
https://github.com/mysteriumnetwork/node/blob/1.39.5/tequilapi/endpoints/transactor.go ,
https://github.com/mysteriumnetwork/node/blob/1.39.5/tequilapi/endpoints/connection.go ,
https://github.com/mysteriumnetwork/node/blob/1.39.5/tequilapi/contract/connection.go ,
https://github.com/mysteriumnetwork/node/blob/1.39.5/tequilapi/endpoints/proposals.go ,
https://github.com/mysteriumnetwork/node/blob/1.39.5/core/connection/connection_validator.go ,
https://github.com/mysteriumnetwork/node/blob/1.39.5/config/flags_service_start.go ,
https://github.com/mysteriumnetwork/node/blob/1.39.5/config/flags_directory.go ,
https://help.mystnodes.com/en/articles/3777670-running-a-mystnodes-as-docker-image-on-linux-host .

## [грабли] Kill-switch ноды не касается транзита; шлюз `dpn` держит свои правила

**Контекст:** Stage 8, gateway-контейнер `dpn` (`images/myst-consumer`), 2026-09-13.
**Суть:** цепочка `MYST_CONSUMER_KILL_SWITCH` (`firewall/outgoing_firewall_iptables.go`, 1.39.5) подключается в `OUTPUT` с `-s <outbound IP>` — она закрывает трафик самого контейнера, а транзит устройств LAN идёт через `FORWARD`.
Снято исполнением: у штатного `mysteriumnetwork/myst:1.39.5-alpine` с `--firewall.killSwitch.always daemon` без сессии `iptables-save` показывает только nat-цепочку `MYST` (DNAT 10/8, 172.16/12, 192.168/16, 127/8 в 240.0.0.1), без правил `FORWARD`; `nft` в образе нет.
Обёртка ставит таблицу `inet vibedpn_dpn`: `forward` с политикой drop — из `eth0` только в другой интерфейс (туннель, имя не важно), ответы по conntrack, MSS clamp; `postrouting` — NAT в туннель; `input` — TequilAPI 4050 только с `lo` и с 10.77.0.1 (хост на мосту `vibedpn0`).
На стенде `home` с эмуляцией NAT провайдера устройство LAN без сессии не выходило и со штатным образом — причина не установлена (см. `docs/decisions.md`, решение 5).
**Источники:** https://github.com/mysteriumnetwork/node/blob/1.39.5/firewall/outgoing_firewall_iptables.go .

## [провайдер] Чем пополняется consumer: MYST на адресе канала

**Контекст:** Stage 8, README «Как пополнить выход через Mysterium», 2026-09-13.
**Суть:** у identity в `GET /identities/{id}` есть `channel_address` (`tequilapi/contract/identity.go`). Пока identity не зарегистрирована, её баланс — это баланс токена MYST на этом адресе: `getUnregisteredChannelBalance` берёт `GetActiveChannelAddress` и спрашивает `GetMystBalance` по контракту MYST (`session/pingpong/consumer_balance_tracker.go`, node 1.39.5). Поэтому пополнение — перевод MYST сети Polygon на `channel_address`.
Контракт MYST на Polygon — `0x1379e8886a944d2d9d440b3d88df536aea08d9f3`, 18 знаков; купить — MEXC, Uniswap V3, Quickswap (справочный центр MystNodes). Второй путь — платёжные шлюзы ноды: `GET /v2/payment-order-gateways`, `POST /v2/identities/{id}/{gw}/payment-order` (`tequilapi/endpoints/pilvytis.go`), в ответе заказа тот же `channel_address`.
**Не проверено:** реальный перевод и регистрация — нужны средства владельца.
**Источники:** https://github.com/mysteriumnetwork/node/blob/1.39.5/session/pingpong/consumer_balance_tracker.go ,
https://github.com/mysteriumnetwork/node/blob/1.39.5/tequilapi/endpoints/pilvytis.go ,
https://help.mystnodes.com/en/articles/8004186-adding-myst-token-to-metamask-on-the-polygon-mainnet ,
https://help.mystnodes.com/en/articles/8004190-where-to-buy-polygon-myst .

## [провайдер] Несколько соединений в одной ноде — только прокси-режимом

**Контекст:** Stage 10, несколько стран Mysterium одновременно (решение 11), 2026-09-14.

**Суть (исходники node 1.39.5, тег `1.39.5`, коммит `c45527af`):**
TequilAPI работает через `connection.MultiManager` (`core/connection/multi.go`): отдельный менеджер соединения на каждый `connect_options.proxy_port`, соединение выбирается параметром `id`.
Какой клиент WireGuard создать, решает глобальный флаг ноды, а не запрос (`services/wireguard/endpoint/wg_client.go`): `--proxymode` → `proxyclient`, иначе клиент ядра, если он поддерживается.
`proxyclient` поднимает WireGuard в netstack — стеке TCP/IP внутри процесса, без интерфейса в ядре — и отдаёт его наружу HTTP-сервером (`net/http`, `newProxyHandler`) на `:<proxy_port>` (адрес задаёт `FlagProxyBindAddress`).

**Как применять:** маршрутизировать трафик LAN через такое соединение, как через туннель, нельзя — только HTTP-прокси, и UDP (QUIC видео) через него не пройдёт.
Страна на соединение в режиме туннеля ядра — это отдельная нода, то есть свой контейнер consumer со своим сетевым пространством.

**Источники:** https://github.com/mysteriumnetwork/node/blob/1.39.5/core/connection/multi.go ; https://github.com/mysteriumnetwork/node/blob/1.39.5/services/wireguard/endpoint/wg_client.go ; https://github.com/mysteriumnetwork/node/blob/1.39.5/services/wireguard/endpoint/proxyclient/client.go ; https://github.com/mysteriumnetwork/node/blob/1.39.5/tequilapi/endpoints/connection.go
