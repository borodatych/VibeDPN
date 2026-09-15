# Провайдер режет TLS к `mysterium.network` по имени сервера

Замер на коробке N100 (Debian 13, домашний провайдер, Россия), 2026-09-15.

## Что видно

`myst-provider` и `myst-consumer` уходят в перезапуск по кругу с кодом 1: нода не получает адрес hermes.
В логе ноды: запрос к `https://observer.mysterium.network/api/v1/observed/hermes` не отвечает, к `https://polygon1.mysterium.network/` — `net/http: TLS handshake timeout`, затем `Failed to execute command: could not get hermes URL`.

## Как отличили от MTU

С хоста коробки:
- DNS отвечает, TCP на 443 к адресам Mysterium (46.224.211.253, 116.203.130.98, 159.69.15.34) открывается, ping проходит;
- `curl -v` отправляет `Client hello` (1581 байт) и больше ничего не получает до таймаута;
- тот же адрес с другим именем в TLS (`curl --resolve example.com:443:46.224.211.253 https://example.com/ -k`) — рукопожатие за 0,2 с, ответ 404;
- настоящее имя по маршруту с MTU 1400 до того же адреса — снова таймаут.

Вывод: блокировка по SNI, не размер пакетов.
Попутно: путь этого провайдера пропускает пакеты не больше 1480 байт (`ping -M do -s 1452` проходит, `-s 1472` — нет) при MTU 1500 на интерфейсе; на этот сбой не влияет, но для LAN за коробкой важен MSS clamping.

## Что из этого следует

Нода Mysterium на такой коробке напрямую не работает ни как provider, ни как consumer.
Её трафик к сервисам Mysterium должен идти в обход провайдера — например, через туннель к своей VPS (роли `client` и `vps`).

## Что проходит мимо блокировки без своей VPS (2026-09-15)

Проверено с коробки, всё — на `observer.mysterium.network` и соседях:
- все 11 служебных имён `*.mysterium.network` по HTTPS не отвечают; публичные RPC Polygon (`polygon.drpc.org`, `polygon-rpc.publicnode.com`) отвечают за 0,1 с; брокер NATS `broker.mysterium.network:4222` без TLS присылает `INFO`;
- тот же адрес без имени в TLS и с `Host: observer.mysterium.network` отдаёт настоящий ответ (`200`, список hermes); так же отвечают discovery, location, polygon1 (`eth_chainId` = `0x89`) — сервисы стоят за одним ingress и выбираются по `Host`;
- но без имени в TLS ingress отдаёт «Kubernetes Ingress Controller Fake Certificate» (`DNS:ingress.local`): настоящего собеседника так не проверить, это не годится;
- разрезать ClientHello на два TCP-сегмента (граница внутри имени) — не помогает, таймаут;
- **разрезать ClientHello на две TLS-записи** (граница внутри имени) — рукопожатие проходит, сертификат `observer.mysterium.network` проверяется полностью;
- **имя в другом регистре** (`Observer.Mysterium.Network`) — проходит так же, с полной проверкой сертификата.

Вывод: фильтр сравнивает имя в первой TLS-записи точной строкой; ретранслятор на самой коробке, который режет первую запись (или меняет регистр имени), проводит ноду к сервисам Mysterium без подмены сертификатов и без VPS.

## Флаги ноды 1.39.5 для служебных адресов

Источник: https://github.com/mysteriumnetwork/node/blob/1.39.5/metadata/network.go , https://github.com/mysteriumnetwork/node/blob/1.39.5/config/flags_node.go , https://github.com/mysteriumnetwork/node/blob/1.39.5/config/flags_location.go
- `--discovery.address`, `--broker-address`, `--transactor.address`, `--affiliator.address`, `--pilvytis.address`, `--observer.address`, `--access-policy.address`, `--location.address`, `--quality.address`, `--feedback.url`, `--ether.client.rpcl1`, `--ether.client.rpcl2`; `--quality.type=none`, `--location.type=manual` отключают необязательные сервисы (имена сверить через `myst --help`).
- Запуск останавливается без брокера и без URL hermes: URL читается из контракта через L2 RPC, затем у observer (https://github.com/mysteriumnetwork/node/blob/1.39.5/session/pingpong/hermes_url_getter.go , https://github.com/mysteriumnetwork/node/blob/1.39.5/cmd/di.go ).
- Официальных средств обхода цензуры (фронтинг, зеркала, обфускация) в исходниках и документации не найдено.

## Проверено на коробке с настоящими нодами (2026-09-15)

После включения `upstreams.dpn` и `provider` с сервисом `myst-relay` (решение 22):
- оба узла поднялись и работают без единого перезапуска (до этого 6 и 7 подряд);
- в логе выхода ноль строк `could not get hermes URL` — именно на ней запуск обрывался;
- ретранслятор сам перешёл на разрез для `transactor`, `location`, `pilvytis` и `hermes3`;
- `/status`: identity создана, поле ошибки пустое, статус `Unregistered`, баланс 0 — это уже экономика сети, а не блокировка.

Значит, для работы ноды в такой сети свой сервер за границей не нужен.

