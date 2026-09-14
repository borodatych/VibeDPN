# AdGuard Home: пересылка доменов своему резолверу, кэш и журнал запросов

## [провайдер] `[/домен/]апстрим` забирает и поддомены, кэш уважает TTL, querylog видит клиента

**Контекст:** Stage 10, smart-режим по решению 11 (вариант 2): AdGuard впереди, домены правил — резолверу ядра, журнал по устройствам — для снифера и автообучения, 2026-09-14.

**Суть (исполнением, `adguard/adguardhome:v0.107.79` и крошечный DNS-ответчик на `127.0.0.1:5354` с TTL 60, colima VM):**
`upstream_dns: [1.1.1.1, "[/example.com/]127.0.0.1:5354"]`.
Запрос `example.com` с `127.0.0.11` и `www.example.com` с `127.0.0.12` — оба ушли в ответчик (он записал `asked example.com`, `asked www.example.com`): правило домена покрывает поддомены.
Повторный `www.example.com` с `127.0.0.13` через 3 с — ответчик не спрошен, ответ из кэша с TTL `57`: AdGuard кэширует ответ своего апстрима и отсчитывает его TTL.
`GET /control/querylog?limit=5` — на каждый запрос `client` (адрес устройства), `name`, `time` с наносекундами, `upstream: "127.0.0.1:5354"`, `cached: true|false`, `elapsedMs`; запрос из кэша тоже записан, с клиентом.

**Как применять:**
резолвер ядра получает запросы от адреса AdGuard и устройства не знает — журнал по устройствам берётся из `querylog`;
TTL ответа задаёт резолвер ядра, таймаут элемента nft-набора — не меньше этого TTL и продлевается при каждом ответе, иначе AdGuard отдаст из кэша адрес, которого в наборе уже нет.

**Документация:** синтаксис `[/domain1/domain2/]upstream`, несколько апстримов через пробел с v0.107.41, `#` — серверы по умолчанию, `[/*.example.local/]` — только поддомены; обычный DNS с портом — `127.0.0.1:5354` или `udp://…`.

**Источники:** https://github.com/AdguardTeam/AdGuardHome/wiki/Configuration (upstream_dns).

## [провайдер] API журнала запросов: курсор и поля

**Суть (openapi AdGuard Home v0.107.79):** `GET /control/querylog` принимает `older_than` (курсор по времени), `offset`, `limit`, `search` (домен или адрес клиента); `response_status` устарел, вместо него `reason`.
Ответ — `data` (записи) и `oldest` (время самой старой записи страницы, для следующего курсора).
Запись: `client`, `client_info`, `time` (начало обработки), `question` (`name`, `type`, `class`), `answer` (записи с `value`, `type`, `ttl`), `cached`, `upstream`, `elapsedMs`, `reason`.

## [провайдер] Запись журнала запросов как она есть

**Суть (исполнением, v0.107.79, запросы с `127.0.0.21` и `127.0.0.22`, ответ сохранён в `core/tests/fixtures/adguard_querylog_v0_107_79.json`, 2026-09-14):**
`GET /control/querylog?limit=4` отдаёт записи **от новых к старым**.
`time` — строка RFC 3339 в UTC с наносекундами: `2026-09-14T07:53:55.818445813Z`.
Имя и тип — в `question` (`{"class":"IN","name":"www.example.com","type":"AAAA"}`); `client` — адрес устройства; `cached: true` у ответа из кэша; `upstream: "1.1.1.1:53"`; `status: "NOERROR"`, `reason: "NotFilteredNotFound"`.
У ответа без записей (пустой AAAA) поля `answer` в записи **нет вовсе**; иначе `answer` — список `{"type":"A","value":"104.20.23.154","ttl":68}`.

## [провайдер] dnspython: DoH через httpx

**Суть (документация dnspython 2.8.0, ISC, чистый Python, Python ≥3.10):** `dns.query.https(q, where, timeout, port=443, …, session=httpx.Client, path="/dns-query", post=True, bootstrap_address=…, http_version=…)` — DoH идёт через `httpx`, можно передать готовый клиент и адрес, чтобы не разрешать имя апстрима; `dns.query.udp(q, where, timeout, port=53, …)` — обычный DNS.
Альтернатива dnslib 0.9.26 (BSD) только кодирует и разбирает пакеты, без клиента DoH.
**Грабля (исполнением, образ ядра на Python 3.12, 2026-09-14):** без extra `doh` DoH через httpx молча не работает.
`dns._features` требует для `doh` пакеты `httpcore>=1.0.0`, `httpx>=0.28.0` и `h2>=4.2.0`; в образе были httpx и httpcore, но не `h2` — `have("doh")` возвращал `False`.
Тогда `https()` при `http_version=DEFAULT` уходит в ветку HTTP/3 и с переданным `httpx.Client` падает: `ValueError: session parameter must be a dns.quic.SyncQuicConnection.`
Зависимость ставится как `dnspython[doh]` — она тянет `h2`, `hpack`, `hyperframe`.

**Источники:** https://raw.githubusercontent.com/AdguardTeam/AdGuardHome/v0.107.79/openapi/openapi.yaml ; https://dnspython.readthedocs.io/en/stable/query.html ; https://pypi.org/pypi/dnspython/json ; https://pypi.org/pypi/dnslib/json

## [провайдер] Смена `upstream_dns` через API перезапускает DNS-сервер

**Суть (исходники v0.107.79, `internal/dnsforward/http.go`):** `handleSetConfig` вызывает `setConfig`; если изменилось `UpstreamDNS`, `setConfigRestartable` возвращает `shouldRestart`, и после `ConfModifier.Apply` идёт `s.Reconfigure` — перезапуск DNS-сервера.
Так же перезапускают: `LocalPTRResolvers`, `UpstreamDNSFileName`, `BootstrapDNS`, `FallbackDNS`, `EDNSClientSubnet.Enabled`, настройки кэша (`CacheEnabled`, `CacheSize`, `CacheMinTTL`, `CacheMaxTTL`, `CacheOptimistic`), `UseRDNS`, `UsePrivateRDNS`, лимиты запросов, `UpstreamTimeout`.
Без перезапуска применяются: `BlockingMode`, `BlockedResponseTTL`, `ProtectionEnabled`, `UpstreamMode`, `EDNSCSUseCustom`, `EnableDNSSEC`, `AAAADisabled`.

**Как применять:** список доменов в `upstream_dns` нельзя менять при каждом выученном CDN — это перезапуск DNS всего дома; менять можно только редко (смена режима).

**Источник:** https://github.com/AdguardTeam/AdGuardHome/blob/v0.107.79/internal/dnsforward/http.go

## [провайдер] `fallback_dns`: закрытый порт апстрима — ответ сразу

**Суть (исполнением, v0.107.79, `upstream_dns: [127.0.0.1:5399]` без слушателя, `fallback_dns: [1.1.1.1]`, кэш выключен, colima VM):**
AdGuard пишет `dnsproxy: exchange failed upstream=127.0.0.1:5399 … read: connection refused` и отвечает через запасной сервер: `example.com` — 2 ответа, rcode 0, за 0.22 с при `upstream_timeout: 10s`; при `1s` — 0.36 и 0.22 с.
Отказ соединения на loopback приходит мгновенно, таймаут не ждётся; ждать `upstream_timeout` пришлось бы, только если апстрим принимает запросы и молчит.
Документация: «List of fallback DNS servers used when upstream DNS servers are not responding» (с v0.107.37).

**Как применять:** резолвер ядра на loopback как апстрим безопасен для дома: остановленное ядро не оставляет устройства без DNS.

**Источник:** https://github.com/AdguardTeam/AdGuardHome/wiki/Configuration (fallback_dns).
