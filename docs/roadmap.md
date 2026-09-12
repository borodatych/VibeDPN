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
- [ ] `vibedpn init`: детект интерфейсов/подсети/wg-модуля, вопросы только роль + пароль
      (+ peer-config), запись `config.yaml`, `.env`, `COMPOSE_PROFILES`
- [ ] `vibedpn up|down|restart|status|logs` поверх compose
- [ ] `vibedpn doctor` v1: wg-модуль, ip_forward, занятые порты 53/51820, docker жив

## Stage 2 — Роль vps: нода

- [ ] `myst-provider` контейнер с published-портами, volume, флагами из §10 idea.md (актуальные —
      [knowledge/myst/node.md](knowledge/myst/node.md)); пароль TequilAPI из `secrets/`, не `myst/mystberry`
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
- [ ] `engine/router.py`: nft-шаблоны, fwmark, `ip rule`, таблица `vps`; режимы `off` и `full`;
      идемпотентный apply
- [ ] nft: LAN не достигает адресов `10.77.0.0/24` напрямую (только транзит через шлюзы) — обязательное
      следствие режима `nat-unprotected` сети шлюзов ([knowledge/docker/directRouting.md](knowledge/docker/directRouting.md))
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

- [ ] Каркас React по стеку §4 idea.md, экран входа (пароль — тот же, что у `/api/` со Stage 4), слушает только LAN
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
- [ ] `docs/troubleshooting.md` по реальным вопросам из чата
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
