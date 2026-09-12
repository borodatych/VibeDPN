# Roadmap VibeDPN

Один чекбокс — одна итерация; стадия закрыта, когда прошли её проверки (`CLAUDE.md`).
Выполнено — отмечается `[x]` с датой и веткой. Концепт и архитектура — [idea.md](idea.md);
грабли и проверенные факты — [knowledge/](knowledge/README.md).

## Stage 0 — Каркас

- [x] **Структура репо, `.vibe/` со стандартным набором + `vibedpn.mdc`** — ✅ (2026-09-11, `next`) дерево по §5 idea.md
      (пути доков — по соглашениям проекта, см. [README.md](README.md)), `.vibe/` из канона
      VibeBrains, правила §11 в `.vibe/rules/vibedpn.mdc` и `CLAUDE.md`
- [x] **`compose.yaml` со всеми сервисами и профилями** — ✅ (2026-09-11, `next`) семь сервисов, сеть `vibedpn-upstreams` (`nat-unprotected`, статические IP шлюзов), образы `core`/`wg`/`ui` собираются и проходят smoke (core `/health` через nginx-прокси ui); entrypoint `wg` — контракт режимов, реализация в Stage 3; живая техспека `docs/techSpec.md`, мануал среды `docs/manuals/devSetup.md`
- [x] **`config.example.yaml` + Pydantic-модель `config.py`** — ✅ (2026-09-11, `next`) валидация ролей и профилей,
      спека формата [manuals/configSpec.md](manuals/configSpec.md)
- [x] **CI** — ✅ (2026-09-11, `next`) lint (ruff, mypy strict, eslint через `npm run lint` когда появится `ui/package.json`), pytest, shellcheck, actionlint, `compose config`, buildx multi-arch (amd64+arm64) сборка `core`, `wg`, `ui` в GHCR; первый прогон в GitHub 2026-09-12 (run 34690322430) зелёный целиком, включая multi-arch сборку и публикацию в GHCR
- [x] **README** — ✅ (2026-09-11, `next`) три сценария в одном абзаце каждый, статус и предупреждение об exit-ноде (заполняется по мере стадий)
- [x] **Репозиторий на GitHub** — ✅ (2026-09-12, `next`) публичный `github.com/borodatych/VibeDPN`, образы `ghcr.io/borodatych/vibedpn-{core,wg,ui}`; VibeBrainsProjects из kickoff не используется — решение владельца
- [x] **Ревью Stage 0** — ✅ (2026-09-11, `next`) состязательное ревью шестью линзами: главная находка — `trusted_host_interfaces` не пропускает транзит в бридж, сеть переведена на `nat-unprotected` с обязательным nft-drop прямого доступа в Stage 4; `peer_config` убран из конфига (фиксированный `secrets/wg-client.conf`), bind-mount файлов без создания каталогов, чистые ошибки конфига у `vibedpn-core`, IPv4-валидация `endpoint`, проверка `lan_address` без перебора /8, пин ruff, `concurrency` и пиновый actionlint в CI, `latest` строго для `main`

## Stage 1 — CLI и install

- [x] **`install.sh`** — ✅ (2026-09-12, `next`) детект ОС/арх (Debian 12/13, Raspberry Pi OS 64-bit, amd64/arm64), Docker Engine + Compose из официального apt-репо (deb822), clone в `/opt/vibedpn`, venv на системном Python (floor опущен до 3.11 ради bookworm), зависимости по `core/requirements.txt` с sha256, симлинк, группа `docker`; идемпотентен; тест в CI дважды в чистых bookworm/trixie-контейнерах, матрица Python 3.11/3.12/3.13; мануал [manuals/installation.md](manuals/installation.md)
- [x] **`vibedpn init`** — ✅ (2026-09-12, `next`) детект интерфейса с default route, адреса и подсети
      (`ip -j`, парсеры на реальных фикстурах), публичного адреса для vps и модуля `wireguard`;
      вопросы только роль, пароль UI и peer-файл, всё задаваемо флагами; `config.yaml` рендерится из
      шаблона с пояснениями (образец `config.example.yaml` — его рендер, тест держит их равными),
      `.env` из `Config.env_vars()`, `secrets/htpasswd` (bcrypt, проверен с nginx `auth_basic`),
      `secrets/wg-client.conf` 600; повторный запуск — отказ без `--force`, бэкап с ним; `init`
      прогоняется в CI-тесте установки. Ревью (3 линзы + скептик): лимит bcrypt 72 байта с понятной
      ошибкой, все отказы через `error:` без трассировок, сборка содержимого до первой записи,
      ранние отказы до вопросов, флаги чужой роли, `~` в промпте, секреты прежней роли в `.bak`,
      честная негативная проверка в CI
- [x] **`vibedpn up|down|restart|status|logs`** — ✅ (2026-09-12, `next`) поверх `docker compose --project-directory`; `up -d --remove-orphans` с пересборкой `.env` из `config.yaml`, `down` со всеми профилями, `restart` = up + restart (bind-mount конфига пересоздание не вызывает), `status` из конфига и `ps --format json`, `logs` с `-f`/`--tail`; preflight переводит ошибки Docker (нет CLI, нет демона, нет прав на сокет) в одну строку; smoke на colima: up только `core` → healthy → logs → restart → down. Ревью (2 линзы + скептик): `init` под sudo отдаёт `config.yaml`/`.env` пользователю (иначе `up` без sudo падал), `up`/`restart` гасят контейнеры выпавших профилей (`--remove-orphans` их не трогает — проверено), тег образов из ветки чекаута (`next` → `:next`, а не несуществующий `latest`)
- [x] **`vibedpn doctor` v1** — ✅ (2026-09-12, `next`) таблица проверок с вердиктом, деталью и подсказкой: config/.env/secrets, модули `wireguard` (fail только при настроенном туннеле) и `nf_tables`, `ip_forward`, порты роли по `ss -H -lntup` с учётом своих контейнеров и заглушки resolved, Docker и сервисы; `--json`; exit 1 при fail; парсеры на реальных фикстурах, CI-тест установки гоняет `doctor`; только проверяет, не чинит (§11.2). Ревью (2 линзы + скептик): неснятый факт — `warn`, не ложный вердикт (root-only `secrets/`, `modprobe` вне PATH, отсутствие `ss`, недоступный Docker при занятых портах), упавший контейнер — `fail`, подсказка при битом конфиге ведёт к правке, а не к `init --force`, порты ноды в проверке, модуль WireGuard обязателен только для профилей wg-*

## Stage 2 — Роль vps: нода

- [x] **`myst-provider` контейнер** — ✅ (2026-09-12, `next`) сервис с published-портами (loopback 4449/4050, UDP-диапазон), томом `data/myst-provider`, актуальными флагами; пароль панели ноды — bcrypt-файл `nodeui-pass` от `init` (нода читает его при каждом входе, проверено на 1.39.5), пароль спрашивается для всех ролей; TequilAPI, как выяснилось, без аутентификации вовсе — защита сетевая (loopback, nft в Stage 4/8); регистрация и клейм — чекбокс 4 на реальной VPS. Ревью (2 линзы + скептик): порог Docker Engine ≥ 28.0.0 в `install.sh`, `preflight` и `doctor` (до 28 loopback-порты были видны соседям по L2), `up`/`restart` отказываются без `nodeui-pass` (иначе нода молча ставит `mystberry`), `--tequilapi.allowed-hostnames=.` убран (отключал защиту от DNS-rebinding), `nodeui-pass` прежней роли откладывается в `.bak`, факты о секретах в `doctor` потрёхзначные по файлам
- [x] **nftables baseline VPS** — ✅ (2026-09-12, `next`) секция `firewall` (только vps: `ssh_ports` из `sshd_config` через `init`, `allow_tcp/udp`), шаблон `firewall.nft.j2` → таблица `inet vibedpn` с input policy drop (ssh, wg, UDP ноды, `wg0`, ICMP), `engine/router.py` рендерит, проверяет `nft -c`, применяет одной транзакцией идемпотентно, отказывается без правила для ssh; `core` применяет при старте и падает с EX_CONFIG при ошибке; `doctor` проверяет загруженность таблицы; CI применяет ruleset дважды в контейнере с NET_ADMIN
- [ ] `GET /provider/stats` через TequilAPI; `vibedpn status` показывает состояние ноды
- [ ] Проверка: нода видна и заклеймлена в mystnodes.com, инструкция клейма в README

## Stage 3 — Приватный туннель

- [ ] Образ `vibedpn/wg`, entrypoint `server|client`, kill-switch в режиме client
- [ ] `wg-server` на VPS (wg0 10.78.0.1/24), ключи в `core`, персист в volume
- [ ] `vibedpn peer add|rm|list|export` → `.conf` + QR в терминале
- [ ] NodeUI 4449 и `core` API доступны с домашней стороны через wg0 и больше ниоткуда

## Stage 4 — Роль client, sidecar, аплинк vps

- [ ] `wg-client` как gateway-контейнер (10.77.0.10) с ip_forward + MASQUERADE + kill-switch
- [ ] `engine/router.py`: nft-шаблоны, fwmark, `ip rule`, таблица `vps`; режимы `off` и `full`;
      идемпотентный apply
- [ ] nft: LAN не достигает адресов `10.77.0.0/24` напрямую (только транзит через шлюзы) — обязательное
      следствие режима `nat-unprotected` сети шлюзов ([knowledge/docker/directRouting.md](knowledge/docker/directRouting.md));
      транзит через FORWARD разрешён явно (Docker ставит DROP на пересылку — [knowledge/linux/doctorProbes.md](knowledge/linux/doctorProbes.md))
- [ ] Авторизация `/api/` в `ui` (nginx `auth_basic`, пароль из `init`) — до появления `PUT /mode`;
      перенесено из Stage 6, где остаётся экран входа
- [ ] `vibedpn mode off|full`, `vibedpn upstream vps`
- [ ] AdGuard Home на 53 LAN-интерфейса, DoH-апстрим; README: как указать шлюз/DNS на устройстве
      и на типовом роутере
- [ ] E2E-стенд `tests/e2e`: fake-vps + box + lan-client; тесты exit IP / mode off / kill-switch
- [ ] `vibedpn doctor` v2: exit IP по каждому аплинку, утечка DNS

## Stage 5 — Политики по устройствам

- [ ] Обнаружение устройств LAN (ARP/neighbour + DHCP-lease при наличии), имена, персист в SQLite
- [ ] nft-сеты `devices_vps|dpn|bypass|block`, override поверх режима
- [ ] `vibedpn device set`, `GET/PUT /devices`
- [ ] E2E: два lan-client с разными политиками

## Stage 6 — UI v1

> **Решение владельца 2026-09-12 (уточнено тем же днём):** UI — полноценное приложение на start0
> (Point0 + Prisma + better-auth), не тонкий SPA; Point0 нравится владельцу, автор его развивает.
> Вариантов два, и оба ведутся параллельно, ни один пока не отсекается: полный — для N100,
> обрезанный — для Raspberry Pi; выбор — по ходу, когда оба будут в руках. Минимум функций:
> человеко-понятный мастер с выбором входящего и исходящего интерфейса для одной коробки.

- [ ] План Stage 6: как устроить два варианта start0-приложения из одной кодовой базы (что именно
      режется для Pi: БД, better-auth, набор экранов или только сборка), стоимость на Pi по памяти
      и CPU, как оба образа собираются в CI и выбираются в `compose.yaml`
- [ ] Каркас start0-приложения (полный вариант), экран входа (пароль — тот же, что у `/api/` со
      Stage 4), слушает только LAN
- [ ] Обрезанный вариант для Raspberry Pi из той же кодовой базы
- [ ] Экран статуса: аплинки, kill-switch, режим, переключатели
- [ ] Список устройств с политиками
- [ ] Вкладка ноды: статистика provider (роль home/vps)

## Stage 7 — Роль home (all-in-one)

- [ ] Профильный пресет `home`: provider + consumer + router + dns + ui на одной коробке
- [ ] Проверка отсутствия петли: трафик provider уходит в WAN напрямую, не через аплинки
- [ ] Provider за NAT: инструкция по пробросу портов + вариант с natpunching, `doctor` проверяет
      достижимость портов
- [ ] README: сценарий «одна коробка»

## Stage 8 — Аплинк dpn (Mysterium consumer)

- [ ] Ответы на вопросы §10 idea.md «Обязательно уточнить» зафиксированы в `docs/knowledge/myst/`
      с URL источников
- [ ] `myst-consumer` gateway-контейнер (10.77.0.20): identity, регистрация, connect через
      TequilAPI, kill-switch; пароль TequilAPI из `secrets/` вместо `myst/mystberry`
- [ ] `engine/myst.py`: proposals → список стран, `PUT /dpn/country`, `vibedpn upstream dpn`
- [ ] Таблица `dpn` в router-engine, переключение аплинка без разрыва bypass-устройств
- [ ] UI: выбор страны, баланс MYST consumer-identity
- [ ] README: как пополнить consumer (Polygon), сколько стоит

## Stage 9 — Gateway-режим (2 порта)

> **Решение владельца 2026-09-12:** целевое железо — N100 с одним LAN-портом и Wi-Fi: LAN-порт —
> входящий (WAN), Wi-Fi — точка доступа для домашних устройств. Пункт «Wi-Fi точка доступа» перенесён
> из «Предложений» сюда.

- [ ] `network.mode: gateway`: WAN/LAN интерфейсы, dnsmasq DHCP на LAN, NAT
- [ ] `init` и UI дают выбрать входящий и исходящий интерфейс из обнаруженных
- [ ] Wi-Fi точка доступа (hostapd) как LAN-сторона gateway-режима
- [ ] E2E: lan-client получает адрес по DHCP от box

## Stage 10 — Smart-режим

- [ ] dnsmasq с `nftset=` перед AdGuard, доменные списки в `config.yaml`
- [ ] `routing.mode: smart`, редактор списков в UI
- [ ] Импорт готовых списков (по URL, с кэшем)

## Stage 11 — Полировка и раздача

- [ ] DNS-запросы AdGuard идут через `default_upstream` в режиме `full`
- [ ] `vibedpn backup|restore|update`, автообновление по таймеру (opt-in)
- [ ] `docs/troubleshooting.md` по реальным вопросам из чата
- [ ] Релиз v0.1.0: теги образов, GitHub Release, одна строка установки в README

## Stage 12 — Образ для Pi (опционально)

- [ ] `pi-gen` пайплайн: готовый `.img` с предустановленным VibeDPN, first-boot запускает `init`

## Предложения (не выполнять без команды оператора)

- Второй DPN-бэкенд: Sentinel dVPN как ещё один gateway-контейнер
- Telegram-бот: алерты «туннель лёг», еженедельный отчёт по заработку ноды
- Несколько VPS-пиров с failover
- Интеграция с fresta: коробка как источник whitelist-конфигов для мобильных
- Web-обновлялка (кнопка «обновить» в UI)
