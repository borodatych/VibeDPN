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

## [провайдер] dnspython: DoH через httpx

**Суть (документация dnspython 2.8.0, ISC, чистый Python, Python ≥3.10):** `dns.query.https(q, where, timeout, port=443, …, session=httpx.Client, path="/dns-query", post=True, bootstrap_address=…, http_version=…)` — DoH идёт через `httpx`, можно передать готовый клиент и адрес, чтобы не разрешать имя апстрима; `dns.query.udp(q, where, timeout, port=53, …)` — обычный DNS.
Альтернатива dnslib 0.9.26 (BSD) только кодирует и разбирает пакеты, без клиента DoH.

**Источники:** https://raw.githubusercontent.com/AdguardTeam/AdGuardHome/v0.107.79/openapi/openapi.yaml ; https://dnspython.readthedocs.io/en/stable/query.html ; https://pypi.org/pypi/dnspython/json ; https://pypi.org/pypi/dnslib/json
