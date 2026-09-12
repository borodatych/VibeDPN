# Установка на коробку

Как поставить VibeDPN на Debian-хост и что при этом происходит. До релиза v0.1.0 ветка `main`
пуста — ставить с `VIBEDPN_BRANCH=next`.

## Предусловия

- Debian 12 (bookworm) или Debian 13 (trixie), либо Raspberry Pi OS **64-bit** (она и есть Debian
  для Docker и для нас); архитектура amd64 или arm64. 32-битная Raspberry Pi OS, Ubuntu, OpenWrt —
  не поддерживаются, скрипт откажется с понятным текстом
- Доступ по `sudo`, интернет с коробки
- Для роли `vps` — сервер с публичным IP; для `home` и `client` — коробка в домашней LAN

## Одна строка

```bash
curl -fsSL https://raw.githubusercontent.com/borodatych/VibeDPN/main/install.sh | sudo bash
```

До релиза:

```bash
curl -fsSL https://raw.githubusercontent.com/borodatych/VibeDPN/next/install.sh | sudo VIBEDPN_BRANCH=next bash
```

## Что делает скрипт

1. Проверяет ОС, релиз и архитектуру
2. Ставит `ca-certificates curl git python3 python3-venv`
3. Ставит Docker Engine и Compose из официального apt-репозитория Docker
   (`/etc/apt/sources.list.d/docker.sources`, ключ `/etc/apt/keyrings/docker.asc`);
   если `docker compose version` уже работает — шаг пропускается
4. Клонирует репозиторий в `/opt/vibedpn` (повторный запуск — fast-forward до свежего `main`)
5. Собирает CLI в `/opt/vibedpn/venv` на системном Python (3.11 в bookworm, 3.13 в trixie):
   зависимости ставятся по `core/requirements.txt` с проверкой sha256, пакет собирается из
   `/opt/vibedpn/core`; ссылка `/usr/local/bin/vibedpn`
6. Добавляет пользователя, вызвавшего `sudo`, в группу `docker` — чтобы `vibedpn up` работал без
   `sudo`. Членство в этой группе равно root на коробке; коробка — выделенное устройство, и это
   осознанная плата за удобство

Скрипт идемпотентен: повторный запуск обновляет клон и CLI, ничего не ломая.

## Переменные

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `VIBEDPN_BRANCH` | `main` | какую ветку ставить |
| `VIBEDPN_REPO` | `https://github.com/borodatych/VibeDPN.git` | откуда клонировать (можно локальный путь) |
| `VIBEDPN_DIR` | `/opt/vibedpn` | куда |

## Проверить

```bash
vibedpn --version
docker compose version
```

## Настроить: `sudo vibedpn init`

Мастер спрашивает только то, что нельзя определить: роль, пароль панелей (от 8 символов, не
длиннее 72 байт в UTF-8 — предел bcrypt, кириллица занимает 2 байта на букву; он же пароль
веб-интерфейса VibeDPN и панели ноды NodeUI — логин там `myst`), для `client` — путь к peer-файлу
с VPS. Флаг чужой роли (`--peer-config`
у `home`, `--endpoint` у `client`) — ошибка, а не молчаливое игнорирование. Остальное детектируется:
интерфейс с маршрутом по умолчанию, его адрес и подсеть, наличие модуля `wireguard` (без него —
предупреждение). Для `vps` публичный адрес берётся с интерфейса; если коробка за NAT и адрес
приватный, мастер спросит `endpoint` (публичный хост или IPv4).

Всё задаваемо флагами — для автоматизации и повторяемости:

```bash
sudo vibedpn init --role vps --endpoint vps.example.com --password-file ~/panels.pw
sudo vibedpn init --role client --peer-config ~/home.conf --password-file ~/panels.pw
```

Что пишется в `/opt/vibedpn`:

| Файл | Что | Права |
|---|---|---|
| `config.yaml` | конфиг с пояснениями, [формат](configSpec.md); режим маршрутизации сразу `off` | 644 |
| `.env` | производные для Compose и `VIBEDPN_TAG` (при повторном `init` тег сохраняется) | 644 |
| `secrets/htpasswd` | `admin:` + bcrypt-хеш пароля — для `auth_basic` в `ui` и API (Stage 4) | 600 |
| `secrets/wg-client.conf` | копия peer-файла (роль `client`) | 600 |
| `data/myst-provider/nodeui-pass` | bcrypt-хеш того же пароля для панели ноды (роли с provider); нода читает его при каждой попытке входа | 600 |

Повторный `init` при существующем `config.yaml` отказывается ещё до вопросов; `--force` заменяет
файл, старый остаётся как `config.yaml.bak`, а секреты прежней роли (например, `wg-client.conf`
после смены `client` → `vps`) откладываются в `*.bak` с теми же правами. В `.env` при повторе
сохраняются `VIBEDPN_TAG`, `MYST_TAG` и `ADGUARD_TAG`. Мастер ничего не пишет, пока не собрал
всё содержимое: любая ошибка ввода оставляет каталог нетронутым.

## Запустить: `vibedpn up`

```bash
vibedpn up          # поднять сервисы роли; .env пересобирается из config.yaml
vibedpn status      # роль, режим, аплинки, контейнеры с health
vibedpn logs core -f
vibedpn restart     # после правки config.yaml руками
vibedpn down        # погасить всё, включая контейнеры неактивных профилей
```

## Проверить: `vibedpn doctor`

Показывает состояние хоста и коробки и подсказывает команду, ничего не меняя: конфиг и `.env`,
секреты роли, модули ядра `wireguard` и `nf_tables`, `net.ipv4.ip_forward`, занятость портов
(53 и панель AdGuard, порт UI, 51820 для `wg-server`, API ядра), доступность Docker и состояние
сервисов роли. Порт, занятый нашим же контейнером, — норма; чужим процессом — `[FAIL]` с его именем
(без `sudo` имя процесса не видно). Заглушка systemd-resolved на `127.0.0.53:53` не мешает:
AdGuard слушает только адрес коробки в LAN. Что нельзя проверить без `sudo` (секреты в root-only
`secrets/`, модули ядра при отсутствии `modprobe` в PATH), становится `[warn]` с подсказкой
`sudo vibedpn doctor`, а не ложным `ok` или `fail`; упавший контейнер — `[FAIL]` с подсказкой
`vibedpn logs`. Код выхода 1 при любом `[FAIL]`; `--json` — для скриптов и будущего UI.

`sudo` не нужен, если после `install.sh` вы перелогинились (группа `docker`); иначе команды
скажут об этом одной строкой. `init` под `sudo` отдаёт `config.yaml` и `.env` вызвавшему
пользователю (по `SUDO_UID`), поэтому `up` и `restart` переписывают `.env` без `sudo`; `secrets/`
остаётся только у root. Под `sudo` переменная `VIBEDPN_DIR` не передаётся — для нестандартного
каталога указывайте `--dir`, как печатает `install.sh`.

Правили `config.yaml` — `vibedpn restart`: он пересобирает `.env` (профили, порты, адрес),
останавливает и удаляет контейнеры профилей, которых у роли больше нет (Compose сам этого не делает:
выключенный профиль для него не «сирота»), пересоздаёт изменившиеся контейнеры и перезапускает
остальные, чтобы они перечитали конфиг. `down` использует все профили, поэтому после смены роли
не остаётся чужих контейнеров.

Тег образов `VIBEDPN_TAG` в `.env` `init` берёт из ветки чекаута: `main` → `latest`, иначе имя
ветки (`next` при установке с `VIBEDPN_BRANCH=next`) — так CI их и публикует. Уже записанный тег
`init --force` и `up` не трогают; переопределить — строкой `VIBEDPN_TAG=` в `.env`.

## Роль `vps`: нода Mysterium

После `vibedpn up` контейнер `myst-provider` стартует с `service --agreed-terms-and-conditions`
и актуальными флагами (`--udp.ports`, `--traversal`), данные ноды — в `data/myst-provider/`.
Панель ноды NodeUI слушает `127.0.0.1:4449`, TequilAPI — `127.0.0.1:4050`; наружу они не
публикуются, доступ с домашней стороны появится через wg-туннель в Stage 3. TequilAPI отвечает
без какой-либо аутентификации — его защищает только то, что он на loopback; пароль NodeUI (логин
`myst`) — тот, что задан в `init`. В `bridge`-сети UPnP не работает; для VPS с публичным IP хватает
`traversal: [manual]`, диапазон UDP открыт публикацией портов. Клейм ноды в mystnodes.com и
проверка на живом сервере — чекбокс 4 этой стадии.

Как дела у ноды, показывает `vibedpn status`: под списком контейнеров идёт блок `node` — версия
и аптайм, вердикт мониторинга сети Mysterium, identity с её статусом регистрации, балансом и
заработком, запущенные сервисы и итоги сессий (сколько, от скольких потребителей, трафик,
заработанные MYST). Сразу после старта identity ещё нет, сервисов нет, мониторинг `unknown` —
это норма: identity нода создаёт не мгновенно, а регистрируется она в сети после клейма
(следующий чекбокс стадии). Строка `node: core is not running`
значит, что ядро не поднято (`vibedpn up`), `node: unavailable (…)` — ядро есть, а нода на
`127.0.0.1:4050` не отвечает (смотреть `vibedpn logs myst-provider`). Ответила не на всё — блок
печатается с тем, что есть, а последняя строка `problems:` называет вопрос, на который ноды не
хватило (статус мониторинга ходит во внешний оракул Mysterium и бывает медленным). Ту же сводку
в JSON отдаёт `GET http://127.0.0.1:4480/provider/stats` ядра — её будет показывать веб-интерфейс.

**Файрвол.** При старте `core` применяет nftables-таблицу `inet vibedpn`: на вход открыты только
порты sshd (`init` спросил их у самого демона — `sshd -T`, — а без него прочитал `sshd_config` с
`Include`, `Port` и `ListenAddress host:port`), порт `wg_server`, UDP-диапазон ноды, трафик из
туннеля `wg0`, ICMP/ICMPv6 и ответы DHCPv6; всё остальное — drop. Свой сервис на той же VPS — в
`firewall.allow_tcp` / `allow_udp` в `config.yaml`, потом `vibedpn restart`. Таблицы Docker не
трогаются. Между перезагрузкой VPS и стартом `core` правил нет — защищает только ключевой ssh.
`doctor` показывает, загружена ли таблица, и сверяет порты, на которых sshd слушает на самом деле,
с `firewall.ssh_ports`: перенесли sshd на другой порт после `init` — `doctor` скажет `[FAIL] ssh`
раньше, чем вы отключитесь. Выключить файрвол — `firewall.enabled: false` и `vibedpn restart`:
`core` при старте снимает таблицу; `vibedpn down` таблицу не трогает — погашенная коробка остаётся
закрытой по последним правилам (ssh и ваши `allow_*` открыты), снять их можно тем же способом
или перезагрузкой. До Stage 3 контейнер `wg-server` в этой роли честно завершается с ошибкой
«not implemented» — `doctor` покажет это как `fail` сервиса.

## Удалить

```bash
sudo rm -rf /opt/vibedpn /usr/local/bin/vibedpn
```

Docker и его репозиторий остаются — они общие для хоста; убрать: `sudo apt-get purge docker-ce
docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin` и удалить
`/etc/apt/sources.list.d/docker.sources`.

## Как это проверяется

CI гоняет `install.sh` дважды в чистых контейнерах `debian:bookworm-slim` и `debian:trixie-slim`
с заглушкой `docker` (`tests/install/docker-stub.sh`): шаг Docker пропускается, остальное — по-настоящему,
включая сборку CLI, проверку `vibedpn --version` через симлинк и `vibedpn init --role vps` с
отказом без `--force` и бэкапом с ним.
