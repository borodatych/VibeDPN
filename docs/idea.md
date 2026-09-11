# VibeDPN — концепт и архитектура (kickoff-промпт)

> Исходный kickoff-промпт проекта от 2026-09-11, без правок. Живые документы, выросшие из него:
> план — [roadmap.md](roadmap.md) (раздел §12 здесь — исторический снимок), правила агента —
> `CLAUDE.md` и `.vibe/rules/vibedpn.mdc` (§11), роли — [roles.md](roles.md), формат конфига —
> [manuals/configSpec.md](manuals/configSpec.md). Пути к докам из §5 приведены к соглашениям
> проекта — соответствие в [README.md](README.md).

> Рабочее название. Альтернативы: VibeGate, VibeNode. Домен не куплен — имя не залочено.
> Репо: `VibeBrainsProjects/vibedpn`. Лицензия: MIT (myst — GPL-3, мы его не форкаем, а запускаем как отдельный контейнер — конфликта нет).

## 1. Что это

Open-source «DPN-коробка» для своих: одна кодовая база, из которой одной командой собирается либо домашний all-in-one роутер, либо связка «нода на VPS + клиент дома». Аналог Deeper Connect, но на своём железе (Raspberry Pi 4/5, мини-ПК на N100, любой Debian-хост) и с открытым dVPN-бэкендом (Mysterium) вместо закрытого AtomOS.

Что делает коробка:

- **Раздаёт канал** в Mysterium Network как exit-нода и получает MYST (роль provider).
- **Гонит трафик** домашних устройств через туннель: либо через собственную VPS (бесплатно, быстро), либо через любую ноду Mysterium с выбором страны (роль consumer).
- **Роутер**: режимы Off / Full / Smart, политика на каждое устройство, kill-switch, адблок через AdGuard Home.
- **Ставится одной строкой** и настраивается мастером `vibedpn init` — целевой пользователь не сетевик, а вайб-кодер из чата.

Что это НЕ: не форк Deeper, не реверс Trident, не свой блокчейн. Протокольный слой — чужой и открытый, мы делаем удобную обвязку и роутер.

## 2. Роли

| Роль | Где стоит | Что запущено | Кому |
|---|---|---|---|
| `home` | дома, одна коробка | provider + consumer + router + dns + ui | хочу всё в одной коробке |
| `vps` | VPS | provider + wg-server + api (headless) | нода отдельно, дома клиент |
| `client` | дома | consumer + wg-client + router + dns + ui | вторая половина связки с `vps` |

Роль = пресет docker-compose профилей. Один `docker-compose.yml`, профили: `provider`, `consumer`, `wg-server`, `wg-client`, `router`, `dns`, `ui`. `vibedpn init --role X` выставляет `COMPOSE_PROFILES` и генерирует `config.yaml`.

Связка `vps` + `client`: у VPS два аплинка наружу — публичная myst-нода (зарабатывает) и приватный WireGuard-сервер для своих домашних коробок (бесплатный туннель). Один VPS может обслуживать несколько домашних клиентов (`vibedpn peer add`).

## 3. Архитектура

### 3.1 Главный принцип: каждый аплинк — gateway-контейнер

Ключевая проблема: myst в режиме consumer перехватывает default route хоста (известная история с потерей интернета на хосте после `connect`). Поэтому **ни один туннель не живёт в netns хоста**. Каждый аплинк — отдельный контейнер со своим сетевым пространством, который работает как шлюз (паттерн gluetun):

```
LAN-устройства ──► [хост: router-engine, nftables + ip rule]
                          │ fwmark → таблица маршрутов
                          ├──► 10.77.0.10  wg-client  (аплинк "vps")  ──► wg0 ──► VPS
                          ├──► 10.77.0.20  myst-consumer (аплинк "dpn") ──► wg ──► нода Mysterium
                          └──► bypass (WAN напрямую)
```

- Docker-сеть `vibedpn-upstreams` (10.77.0.0/24), у каждого upstream-контейнера статический IP.
- Внутри upstream-контейнера: `ip_forward=1`, MASQUERADE в туннельный интерфейс, kill-switch (nft: всё, что не в туннель и не handshake — drop).
- Router-engine на хосте (контейнер `core`, `network_mode: host`, `NET_ADMIN`) только маркирует трафик LAN и рулит его в нужный контейнер. Он никогда не трогает default route хоста.
- Добавить новый бэкенд (Sentinel и т.п.) = добавить ещё один gateway-контейнер и id аплинка. Ядро роутера не меняется.

Provider (myst service) — тоже отдельный контейнер в bridge-режиме с published UDP-портами, как в официальной docker-инструкции Mysterium. Его трафик не проходит через router-engine (он не LAN-источник), поэтому петли «нода гонит чужой трафик через свой же consumer» не возникает.

### 3.2 Компоненты (контейнеры)

| Контейнер | Образ | Профиль | Сеть |
|---|---|---|---|
| `core` | свой, Python 3.12 | всегда | host, NET_ADMIN |
| `ui` | свой, nginx + статика React | `ui` | host (порт только на LAN-интерфейсе) |
| `myst-provider` | `mysteriumnetwork/myst` | `provider` | bridge, ports 4449, 41920-42075/udp, 61920-62075/udp |
| `myst-consumer` | `mysteriumnetwork/myst` | `consumer` | `vibedpn-upstreams` 10.77.0.20, NET_ADMIN |
| `wg-client` | свой `vibedpn/wg` (alpine + wireguard-tools + nftables) | `wg-client` | `vibedpn-upstreams` 10.77.0.10, NET_ADMIN |
| `wg-server` | свой `vibedpn/wg`, режим server | `wg-server` | host, порт 51820/udp |
| `adguard` | `adguard/adguardhome` | `dns` | host, порт 53 на LAN-интерфейсе |

`core` = FastAPI + router-engine + myst-client (TequilAPI) + peer-manager. CLI `vibedpn` на хосте — тонкий клиент к `core` + обёртка над compose.

### 3.3 Сетевые режимы коробки

- **Sidecar** (по умолчанию, 1 сетевой порт): коробка стоит в существующей LAN. Устройства получают её как шлюз/DNS либо руками, либо через DHCP-опцию на основном роутере (в доке — инструкция для типовых роутеров). Первым делом делаем этот режим — меньше движущихся частей, Pi с одним портом.
- **Gateway** (2 порта): WAN ← провайдерский роутер, LAN → свой сегмент, коробка раздаёт DHCP (dnsmasq) и делает NAT. Полный аналог Deeper «в разрыв».

### 3.4 Политики маршрутизации

`routing.mode`:
- `off` — всё bypass.
- `full` — всё через `default_upstream`, кроме device-override.
- `smart` — через аплинк только `smart_domains` (доменные списки) и устройства с явной политикой; остальное bypass.

Политика устройства (по MAC, fallback по IP): `vps | dpn | bypass | block`.

Реализация: nftables set `devices_vps`, `devices_dpn`, `devices_block` → fwmark → `ip rule` → таблицы `vps`/`dpn` с `default via 10.77.0.X`. Smart-домены: dnsmasq с `nftset=` перед AdGuard (dnsmasq резолвит → кладёт IP в nft-set → маркировка). Это стадия 10, не раньше.

### 3.5 Kill-switch

Два уровня:
1. В upstream-контейнере — если туннель лёг, контейнер не выпускает ничего (drop).
2. На хосте — устройства с политикой `vps`/`dpn` в режиме `full` при падении upstream'а НЕ переключаются на bypass молча. UI показывает красный статус. Опция `routing.failopen: false` по умолчанию; `true` — осознанный выбор пользователя.

### 3.6 Приватный туннель VPS ↔ дом

- На VPS: `wg-server` (wg0, 10.78.0.1/24), ключи генерит `core`.
- `vibedpn peer add <name>` на VPS → создаёт пару ключей, добавляет peer, выдаёт `<name>.conf` + QR.
- Дома: `vibedpn init --role client --peer-config <name>.conf` → конфиг уходит в `wg-client`.
- Через этот же туннель VPS отдаёт домой свою admin-панель (NodeUI myst на 4449 и `core` API) — наружу они не торчат.

### 3.7 DNS и адблок

AdGuard Home слушает 53 на LAN-интерфейсе, апстрим — DoH. Стадия 1: DoH-запросы AdGuard'а идут напрямую с хоста. Позже (стадия 11): контейнер AdGuard тоже маршрутизируется через `default_upstream`, чтобы в режиме `full` DNS не утекал мимо туннеля.

## 4. Стек

- Хост: Debian 12/13 или Raspberry Pi OS (64-bit), amd64/arm64. Требуется kernel WireGuard (есть в обоих). OpenWrt — нет: слишком нишево для целевой аудитории.
- Оркестрация: Docker Compose v2, профили.
- `core`: Python 3.12, FastAPI, Pydantic v2, `httpx` (TequilAPI), Jinja2 (шаблоны nft/wg), SQLite (история статусов, сессии, заработок), `config.yaml` — единственный источник правды по конфигу (человекочитаем, бэкапится одним файлом).
- CLI: Python, Typer, ставится `install.sh` в `/opt/vibedpn/venv`, симлинк `/usr/local/bin/vibedpn`.
- UI: React 18 + TypeScript strict + Vite + Tailwind + shadcn/ui + Zustand. Собирается в статику, отдаётся nginx.
- Образ `vibedpn/wg`: alpine, wireguard-tools, nftables, entrypoint с режимами `client|server`.
- Сборка образов: GitHub Actions, multi-arch (amd64 + arm64) через buildx, публикация в GHCR.

## 5. Структура репозитория

```
vibedpn/
├── install.sh                  # curl | bash: docker, git clone, venv, симлинк
├── docker-compose.yml          # все сервисы, разнесены по profiles
├── .env.example
├── config.example.yaml
├── core/                       # Python-пакет vibedpn
│   ├── vibedpn/
│   │   ├── cli.py              # Typer: init, up, down, status, logs, peer, doctor, backup
│   │   ├── api/                # FastAPI роуты
│   │   ├── config.py           # Pydantic-модель config.yaml
│   │   ├── engine/
│   │   │   ├── router.py       # nft/ip rule apply, idempotent
│   │   │   ├── wg.py           # ключи, peers, конфиги
│   │   │   ├── myst.py         # TequilAPI-клиент: consumer connect, provider stats
│   │   │   └── dns.py          # dnsmasq nftset (стадия 10)
│   │   └── templates/          # *.nft.j2, *.conf.j2
│   ├── tests/
│   └── Dockerfile
├── images/wg/                  # Dockerfile + entrypoint.sh
├── ui/                         # React
├── tests/e2e/                  # compose-стенд: fake-vps, box, lan-client
├── docs/
│   ├── README.ru.md            # для друзей: 3 сценария, скриншоты, «что делать если»
│   ├── ROLES.md
│   └── TROUBLESHOOTING.md
├── .vibe/                      # стандартный набор правил + vibedpn.mdc
└── ROADMAP.md
```

## 6. CLI

```
vibedpn init [--role home|vps|client] [--peer-config FILE]   # мастер, пишет config.yaml + .env
vibedpn up | down | restart | status | logs [service]
vibedpn mode off|full|smart
vibedpn upstream vps|dpn
vibedpn device set <mac|ip> vps|dpn|bypass|block [--name ...]
vibedpn peer add|rm|list|export <name>                       # только роль vps
vibedpn doctor            # проверяет: wg-модуль, ip_forward, порты, DNS, состояние туннелей, exit IP
vibedpn backup | restore  # tar с config.yaml, ключами, .env
vibedpn update            # git pull + compose pull + up
```

`init` не задаёт вопросов, ответ на которые можно определить: интерфейсы, подсеть LAN, арх, наличие wg-модуля — детектируются. Спрашивает только роль, пароль UI и (для `client`) путь к peer-конфигу.

## 7. API и UI

`core` API (только на LAN-интерфейсе, Basic/Bearer по паролю из `init`):

```
GET  /status                # роль, режим, аплинки {name, up, exit_ip, latency}, kill-switch
PUT  /mode                  # off|full|smart
PUT  /upstream              # vps|dpn
GET  /devices  PUT /devices/{id}
GET  /dpn/countries  PUT /dpn/country        # через TequilAPI proposals
GET  /provider/stats        # сессии, трафик, заработок (TequilAPI)
GET/POST/DELETE /peers      # роль vps
GET  /doctor
```

UI v1 — один экран: статус аплинков, переключатель Off/Full/Smart, выбор аплинка и страны, список устройств с политикой, ссылка на AdGuard. Заработок ноды — отдельная вкладка. Без «красоты ради красоты», пользователь заходит сюда раз в неделю.

## 8. Безопасность

- UI/API слушают только LAN-интерфейс; на VPS — только через wg0.
- NodeUI myst (4449) наружу не публикуется никогда; доступ через wg-туннель.
- На VPS: nftables baseline (ssh, 51820/udp, myst UDP-диапазоны; всё остальное drop), ssh только по ключу.
- Секреты (`.env`, ключи wg, keystore myst) — `chmod 600`, в `.gitignore`, в бэкап.
- Никакой телеметрии в наш адрес. Метрики ноды идут только в Mysterium.
- В README прямым текстом: exit-нода = чужой трафик с твоего IP, абузы приходят тебе. Рекомендация: provider на VPS, дома — только client.

## 9. Тестирование

- Unit: рендер nft/wg-шаблонов из `config.yaml`, идемпотентность `router.apply()` (двойной apply = тот же результат), Pydantic-валидация конфига.
- E2E (`tests/e2e`, чистый Docker, без железа): `fake-vps` (wg-server + http-эхо, отдающее IP источника), `box` (core + wg-client), `lan-client` (curl через box). Проверки: exit IP = fake-vps; `mode off` → exit IP = свой; `docker stop wg-client` → lan-client не имеет интернета (kill-switch), а не утекает напрямую.
- Ручной чек-лист перед релизом: Pi 4 (arm64) + N100 (amd64), sidecar-режим, реальная VPS.

## 10. Факты и что перепроверить

Проверено на дату kickoff (сентябрь 2026), но перед реализацией стадии агент сверяет с актуальной докой:

- Образ `mysteriumnetwork/myst`; данные в `/var/lib/mysterium-node`; запуск provider: `service --agreed-terms-and-conditions`.
- TequilAPI — `127.0.0.1:4050`, управляет и consumer, и provider стороной; Swagger — `tequilapi.mysterium.network`. NodeUI — 4449.
- Порты provider из официальной docker-инструкции: p2p 41920-42075/udp, wireguard 61920-62075/udp, флаги `--p2p.listen.ports`, `--wireguard.listen.ports`, `--experiment-natpunching=false` при пробросе портов.
- Клейм ноды: API-ключ из профиля mystnodes.com, через NodeUI или onboarding.
- Минимальные требования: 1 ядро, 1 ГБ RAM, 500 МБ диска.

Обязательно уточнить (не полагаться на память):
- Точный TequilAPI-флоу consumer: создание identity, регистрация, пополнение MYST (Polygon), `POST /connection`. Можно ли consumer'у бесплатно ходить через собственную ноду — если да, аплинк `dpn` со своей нодой становится бесплатным и `vps`-туннель для этого случая не нужен.
- Поведение myst consumer внутри контейнера без `--net host`: нужен ли `/dev/net/tun`, какие sysctl.
- Актуальный тег образа и есть ли официальный arm64-манифест (в 2023 был только community-build — если так, собираем свой из `bin/docker/alpine/Dockerfile`).
- Флаг/настройка myst для `datadir` и отключения автообновления внутри контейнера.

## 11. Правила агента (project-specific, поверх стандартного `.vibe/`)

1. Один чекбокс ROADMAP за итерацию. Стадия закрыта только когда прошли её проверки.
2. Всё, что меняет сеть хоста (nft, ip rule, sysctl), — только через `engine/router.py` из шаблонов, идемпотентно, с `vibedpn doctor` до и после. Никаких `iptables` руками в скриптах.
3. Никогда не трогать default route хоста. Если решение требует этого — стоп, возражение оператору.
4. Внешние факты о myst/AdGuard/WireGuard берутся из доки или исходников с указанием URL в commit-сообщении. Память не источник.
5. Секреты не коммитятся; `config.example.yaml` и `.env.example` всегда актуальны.
6. Каждая стадия обновляет `docs/README.ru.md`, если меняет то, что видит пользователь.
7. Раздел «Предложения» — off-limits без команды оператора.

## 12. ROADMAP.md

```markdown
# VibeDPN ROADMAP

## Stage 0 — Каркас
- [ ] Структура репо по §5, `.vibe/` со стандартным набором + `vibedpn.mdc` с правилами §11
- [ ] `docker-compose.yml` со всеми сервисами и профилями (образы-заглушки где своих ещё нет)
- [ ] `config.example.yaml` + Pydantic-модель `config.py` с валидацией ролей/профилей
- [ ] CI: lint (ruff, mypy strict, eslint), pytest, buildx multi-arch сборка `core` и `wg` в GHCR
- [ ] `docs/README.ru.md` — три сценария в одном абзаце каждый (заполняется по мере стадий)

## Stage 1 — CLI и install
- [ ] `install.sh`: детект arch/OS, docker + compose plugin, clone в `/opt/vibedpn`, venv, симлинк
- [ ] `vibedpn init`: детект интерфейсов/подсети/wg-модуля, вопросы только роль + пароль (+ peer-config), запись `config.yaml`, `.env`, `COMPOSE_PROFILES`
- [ ] `vibedpn up|down|restart|status|logs` поверх compose
- [ ] `vibedpn doctor` v1: wg-модуль, ip_forward, занятые порты 53/51820, docker жив

## Stage 2 — Роль vps: нода
- [ ] `myst-provider` контейнер с published-портами, volume, флагами из §10
- [ ] nftables baseline VPS (ssh, wg, myst UDP; остальное drop), применяется `core`
- [ ] `GET /provider/stats` через TequilAPI; `vibedpn status` показывает состояние ноды
- [ ] Проверка: нода видна и заклеймлена в mystnodes.com, инструкция клейма в README

## Stage 3 — Приватный туннель
- [ ] Образ `vibedpn/wg`, entrypoint `server|client`, kill-switch в режиме client
- [ ] `wg-server` на VPS (wg0 10.78.0.1/24), ключи в `core`, персист в volume
- [ ] `vibedpn peer add|rm|list|export` → `.conf` + QR в терминале
- [ ] NodeUI 4449 и `core` API доступны с домашней стороны через wg0 и больше ниоткуда

## Stage 4 — Роль client, sidecar, аплинк vps
- [ ] `wg-client` как gateway-контейнер (10.77.0.10) с ip_forward + MASQUERADE + kill-switch
- [ ] `engine/router.py`: nft-шаблоны, fwmark, `ip rule`, таблица `vps`; режимы `off` и `full`; идемпотентный apply
- [ ] `vibedpn mode off|full`, `vibedpn upstream vps`
- [ ] AdGuard Home на 53 LAN-интерфейса, DoH-апстрим; README: как указать шлюз/DNS на устройстве и на типовом роутере
- [ ] E2E-стенд `tests/e2e`: fake-vps + box + lan-client; тесты exit IP / mode off / kill-switch
- [ ] `vibedpn doctor` v2: exit IP по каждому аплинку, утечка DNS

## Stage 5 — Политики по устройствам
- [ ] Обнаружение устройств LAN (ARP/neighbour + DHCP-lease при наличии), имена, персист в SQLite
- [ ] nft-сеты `devices_vps|dpn|bypass|block`, override поверх режима
- [ ] `vibedpn device set`, `GET/PUT /devices`
- [ ] E2E: два lan-client с разными политиками

## Stage 6 — UI v1
- [ ] Каркас React по стеку §4, авторизация паролем, слушает только LAN
- [ ] Экран статуса: аплинки, kill-switch, режим, переключатели
- [ ] Список устройств с политиками
- [ ] Вкладка ноды: статистика provider (роль home/vps)

## Stage 7 — Роль home (all-in-one)
- [ ] Профильный пресет `home`: provider + consumer + router + dns + ui на одной коробке
- [ ] Проверка отсутствия петли: трафик provider уходит в WAN напрямую, не через аплинки
- [ ] Provider за NAT: инструкция по пробросу портов + вариант с natpunching, `doctor` проверяет достижимость портов
- [ ] README: сценарий «одна коробка»

## Stage 8 — Аплинк dpn (Mysterium consumer)
- [ ] Ответы на вопросы §10 «Обязательно уточнить» зафиксированы в `docs/MYST.md` с URL источников
- [ ] `myst-consumer` gateway-контейнер (10.77.0.20): identity, регистрация, connect через TequilAPI, kill-switch
- [ ] `engine/myst.py`: proposals → список стран, `PUT /dpn/country`, `vibedpn upstream dpn`
- [ ] Таблица `dpn` в router-engine, переключение аплинка без разрыва bypass-устройств
- [ ] UI: выбор страны, баланс MYST consumer-identity
- [ ] README: как пополнить consumer (Polygon), сколько стоит

## Stage 9 — Gateway-режим (2 порта)
- [ ] `network.mode: gateway`: WAN/LAN интерфейсы, dnsmasq DHCP на LAN, NAT
- [ ] `init` детектит два интерфейса и предлагает режим
- [ ] E2E: lan-client получает адрес по DHCP от box

## Stage 10 — Smart-режим
- [ ] dnsmasq с `nftset=` перед AdGuard, доменные списки в `config.yaml`
- [ ] `routing.mode: smart`, редактор списков в UI
- [ ] Импорт готовых списков (по URL, с кэшем)

## Stage 11 — Полировка и раздача
- [ ] DNS-запросы AdGuard идут через `default_upstream` в режиме `full`
- [ ] `vibedpn backup|restore|update`, автообновление по таймеру (opt-in)
- [ ] `docs/TROUBLESHOOTING.md` по реальным вопросам из чата
- [ ] Релиз v0.1.0: теги образов, GitHub Release, одна строка установки в README

## Stage 12 — Образ для Pi (опционально)
- [ ] `pi-gen` пайплайн: готовый `.img` с предустановленным VibeDPN, first-boot запускает `init`

## Предложения (не выполнять без команды оператора)
- Второй DPN-бэкенд: Sentinel dVPN как ещё один gateway-контейнер
- Wi-Fi точка доступа (hostapd) в gateway-режиме
- Telegram-бот: алерты «туннель лёг», еженедельный отчёт по заработку ноды
- Несколько VPS-пиров с failover
- Интеграция с fresta: коробка как источник whitelist-конфигов для мобильных
- Web-обновлялка (кнопка «обновить» в UI)
```
