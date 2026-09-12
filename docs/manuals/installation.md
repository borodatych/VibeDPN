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

Дальше — `sudo vibedpn init` (Stage 1, следующий чекбокс).

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
включая сборку CLI и проверку `vibedpn --version` через симлинк.
