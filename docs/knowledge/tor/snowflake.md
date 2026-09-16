# Блокировки у Ростелекома и Tor через Snowflake: замеры на коробке

Снято 2026-09-17 ночью с коробки `home` (Ростелеком AS12389, адрес 5.139.224.212), только чтение
и тестовые контейнеры. Источники фактов о Tor — репозиторий Tor Browser и пакеты Debian.

## Как режутся цели (с хоста коробки)

Проба: DNS системный и DoH 1.1.1.1, TCP 443, ClientHello целиком и разрезанный на две TLS-записи
(функции `server_name`/`split_hello` ретранслятора ядра).

| Цель | DNS | TCP 443 | ClientHello целиком | разрезанный |
|---|---|---|---|---|
| rutracker.org (Cloudflare) | верный | есть | тишина | ответ, но страница замирает после 23 КБ |
| lostfilm.tv, www.lostfilm.today, nnmclub.to (Cloudflare) | верный | есть | тишина | ответ |
| lostfilm.today, 4pda.to, example.com | верный | есть | ответ | ответ |
| t.me, telegram.org, web.telegram.org, api.telegram.org | верный | **нет** | — | — |
| дата-центры Telegram 149.154.175.50, .167.51, .175.100, .167.91, 91.108.56.130, 91.105.192.100, 95.161.76.100 — порты 443, 80, 5222 | — | **нет** | — | — |
| rutor.info | верный | **нет** | — | — |

DNS не подменён: системный резолвер и DoH отдают одно и то же.
Заблокированное по имени проходит с разрезанным ClientHello, но у rutracker страница (96 КБ через Tor)
замирает после 23 КБ — одного обхода имени мало.
Telegram и rutor закрыты по адресу.

Замерзание на объёме не общее: с того же хоста напрямую 2 МБ с speed.cloudflare.com, proof.ovh.net,
github.com, deb.debian.org и mirror.yandex.ru приходят за доли секунды; hetzner (speed.hetzner.de,
ash-speed.hetzner.com) не соединяется вовсе.
Ответы `discovery.mysterium.network` через ретранслятор ядра (разрезанный ClientHello) — 16 КБ за
полсекунды и тишина до таймаута; consumer из-за этого получает 0 предложений.

## Tor

- Встроенные мосты Tor Browser (`projects/tor-expert-bundle/pt_config.json`,
  https://gitlab.torproject.org/tpo/applications/tor-browser-build/-/raw/main/projects/tor-expert-bundle/pt_config.json):
  obfs4 — 7 шт., snowflake — 2, meek — 1; рекомендованный по умолчанию — obfs4.
- **obfs4** с Ростелекома: все мосты `general SOCKS server failure`, не подключается.
- **Snowflake**: брокер `snowflake-broker.torproject.net` и фронт CDN77 (`1098762253.rsc.cdn77.org`)
  открыты; `Bootstrapped 100%` за ~1–3 минуты (однажды стоял на 71 % несколько минут и дошёл).
- Через Snowflake: rutracker.org/forum — 200, 96 КБ за 2.3 с; www.lostfilm.today — 200;
  rutor.info — 200; web.telegram.org — 200; TCP к дата-центрам Telegram — открыт.
  5 МБ с speed.cloudflare.com — 145 КБ/с (около 1.2 Мбит/с).
- Пакеты Debian trixie: `tor` 0.4.9.12, `obfs4proxy`, `snowflake-client` (сборка 2025-06).
  `lyrebird` и `webtunnel` в trixie нет — мосты webtunnel образ не поддерживает.
- В `debian:trixie-slim` пользователь `debian-tor` уже есть (uid 100).

## Прозрачный шлюз в Tor в контейнере

- Маршрутизированный LAN-трафик приходит в контейнер с чужим адресом назначения; `nft` в netns
  контейнера: `prerouting` → `fib daddr type local return`, TCP → `redirect to :9040` (TransPort),
  UDP 53 → `:5353` (DNSPort). TransPort узнаёт исходный адрес через conntrack — отдельной настройки не нужно.
- Выход только у процесса tor: цепочка `output` с `policy drop`, `meta skuid "debian-tor" accept`.
  Транспорты (snowflake-client) tor запускает от того же пользователя — им тоже можно.
- Собственные запросы контейнера (доктор ходит `wget` изнутри) перенаправляются в TransPort
  цепочкой `nat output`; встроенный DNS Docker 127.0.0.11 оставлен — иначе транспорты не резолвят фронт.
- Ответы TransPort устройству LAN уходят маршрутом по умолчанию контейнера (мост к хосту), отдельных
  таблиц, как в шлюзе WireGuard, не нужно.
- Проверено на коробке в отдельной сети Docker: клиент с маршрутом по умолчанию через шлюз открыл
  rutracker, lostfilm, rutor, web.telegram.org, TCP к дата-центру Telegram, адрес выхода — узел Tor.

## Готовые списки заблокированного

С коробки (с российского адреса) 2026-09-17; с Mac через зарубежный выход Deeper все три адреса не ответили:
- https://community.antifilter.download/list/domains.lst — 7 КБ, 486 строк, домен в строке; `parse_list` ядра
  берёт 485 доменов; внутри rutracker.org/.ru, lostfilm.tv/.today/.win/.run, nnmclub.to, rutor.info/.is/.org,
  kinozal.tv/.me, 4pda.to, instagram.com. Годится для `routing.lists` без доработок.
- https://antifilter.download/list/domains.lst — 31 МБ, 1.65 млн строк: больше предела `MAX_LIST_BYTES` (16 МиБ).
- https://community.antifilter.download/list/community.lst — 894 записи вида `a.b.c.d/32`: сети, не домены;
  подошли бы для скачиваемых списков сетей, которых у `routing.networks` пока нет.

## Грабли стенда на коробке

- Новая сеть Docker на коробке не выпускает контейнер в интернет (`apt-get update` не прошёл):
  выход в интернет закрыт файрволом коробки. Инструменты для тестового клиента — из уже
  скачанного образа `vibedpn-wg` (busybox `wget`, `ip`, `nc`).
- Colima монтирует `/Volumes/Storage`, но не `/private/tmp`: файл в контейнер с Mac — через stdin.
