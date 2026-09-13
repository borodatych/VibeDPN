# Локальная разработка (macOS)

Что нужно, чтобы прогнать все проверки проекта на машине разработчика, и как это проверяется.

## Инструменты

| Инструмент | Зачем | Установка |
|---|---|---|
| `uv` | Python 3.12, зависимости `core/`, запуск ruff/mypy/pytest | `brew install uv`; интерпретаторы и кэш uv у владельца живут на томе Storage (`UV_PYTHON_INSTALL_DIR`, `UV_CACHE_DIR` в `~/.zshrc`) |
| Docker + Compose v2 + buildx | `compose config`, сборка образов | colima (`brew install colima docker docker-compose docker-buildx`), `colima start`; образы собираются под arm64 хоста, amd64 — в CI. См. «Colima» ниже |
| `actionlint` | проверка `.github/workflows` | `brew install actionlint` |
| `shellcheck` | проверка shell-скриптов | `brew install shellcheck`; в CI версия прибита (`SHELLCHECK_VERSION` в `ci.yml`, сейчас 0.11.0) — у раннера своя, более старая, и она спорит с локальной о номерах проверок |

## Порядок

1. `cd core && uv sync --locked` — ставит Python 3.12 и зависимости в `core/.venv`.
2. Проверки ядра: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`.
3. Compose: из корня `docker compose --profile '*' config -q` — валидирует файл со всеми профилями
   без `.env` (дефолты в `compose.yaml` не открывают ничего наружу).
4. Скрипты и workflow: `git ls-files -z '*.sh' | xargs -0 shellcheck` и `actionlint`.
   Поменяли зависимости (`uv add`/`uv lock`) — пересоздать `core/requirements.txt`, иначе CI-гейт
   красный: `cd core && uv export --frozen --no-dev --group build --no-emit-project -o requirements.txt`
   (гейт сравнивает файлы без комментариев: заголовок с путём вывода в них отличается).
   Установку целиком можно прогнать как в CI: `install.sh` в контейнере `debian:trixie-slim` с заглушкой
   `tests/install/docker-stub.sh` (команда — в `.github/workflows/ci.yml`, задача `install`).
5. Панель (`ui/`, Bun ≥ 1.4.2): `cd ui && bun install --frozen-lockfile && bunx prisma generate && bun run generate`,
   затем `bun run check` (типы TypeScript 7 и eslint) и `bun run test:unit && bun run test:dom`. Вариант панели — константа сборки: `UI_VARIANT=lite bun run build:code` (по умолчанию `full`). Запуск на своей машине —
   `ui/docs/setup.md`: локальный Postgres, `env.example` → `.env`, файл `htpasswd.local` с bcrypt-строкой `admin`.
6. Образы: `docker compose --profile '*' build` — собирает `core`, `wg`, `ui` локально. Сборка `ui` требует около 2 ГиБ
   памяти (`dist`): на colima с 2 ГиБ она падает по памяти, образ панели проверяет CI (задача `ui-image`).

Все команды одной строкой — в `CLAUDE.md`, раздел «Проверки перед завершением задачи»; CI
(`.github/workflows/ci.yml`) гоняет то же самое плюс multi-arch сборку в GHCR.

## Colima

Две неочевидности, на которых теряется время:

- **Homebrew-`docker` без buildx.** `docker compose build` падает с «the --mount option requires
  BuildKit»: CLI из brew не содержит плагин buildx. Ставится `brew install docker-buildx` и
  подключается симлинком `ln -sfn "$(brew --prefix)/opt/docker-buildx/bin/docker-buildx"
  ~/.docker/cli-plugins/docker-buildx`; проверка — `docker buildx version`.
- **Bind-mount с тома Storage виден пустой папкой.** Colima по умолчанию монтирует в виртуальную
  машину только `$HOME`; проект живёт на `/Volumes/Storage`, и `-v $PWD/config.yaml:/x` даёт внутри
  пустой каталог. В `~/.colima/default/colima.yaml` секция `mounts` должна перечислять и `~`, и
  `/Volumes/Storage` (`writable: true`), после правки — `colima stop && colima start`. Сборка образов
  этого не требует (контекст CLI отправляет сам), а вот `docker compose up` и smoke-тесты — требуют.

## E2E-стенд

`tests/e2e/router.sh` поднимает на одном Linux-хосте коробку роли `client` из образов репозитория,
fake-VPS и два устройства LAN — и проверяет продукт целиком, включая политики устройств одновременно
(у одного устройства своя политика, у другого — режим, и kill-switch одного аплинка не трогает
соседа, идущего напрямую): адрес выхода в режимах `full` и `off`
(через VPS или напрямую), kill-switch и `failopen`, недоступность сети шлюзов из LAN, `vibedpn mode`,
`doctor` и AdGuard. «Интернет» стенда — своя Docker-сеть 198.18.0.0/24 с веб-сервером, который
отвечает адресом клиента; настоящий интернет нужен только DNS-проверкам (DoH-апстрим AdGuard), их
выключает `VIBEDPN_E2E_OFFLINE=1`. Почему устроено так — [knowledge/ci/e2eStand.md](../knowledge/ci/e2eStand.md).

На macOS — внутри VM colima (путь проекта смонтирован, см. выше), образы собираются тем же демоном:

```bash
docker build -t ghcr.io/borodatych/vibedpn-core:e2e core && docker build -t ghcr.io/borodatych/vibedpn-wg:e2e images/wg
```

```bash
colima ssh -- sh -c 'cd /Volumes/Storage/Projects/VibeCode/VibeDPN && VIBEDPN_TAG=e2e sh tests/e2e/router.sh'
```

Стенд требует sudo, модуль WireGuard и Docker Engine ≥ 28, ставит CLI в свой venv (или берёт
`VIBEDPN_E2E_PYTHON`) и при любом исходе убирает за собой контейнеры, сети, netns `e2e-lanhost`,
мост `lan0` и свои правила в `DOCKER-USER`. В CI его гоняет задача `e2e`.

`tests/e2e/home.sh` — стенд коробки роли `home`: все сервисы роли (ядро, панель с Postgres, AdGuard,
нода и consumer Mysterium) и отсутствие петли — в режиме `full` через `dpn` нода выходит в интернет с тем
же адресом, что и хост. Своя LAN на мосту `lan0`, нужен настоящий интернет (образы Mysterium и эхо-сервис
адреса, `VIBEDPN_E2E_EXIT_URL`). Образ панели локально на VM с 2 ГиБ не соберётся — возьмите
опубликованный и перетегируйте:

```bash
docker pull ghcr.io/borodatych/vibedpn-ui:next-full && docker tag ghcr.io/borodatych/vibedpn-ui:next-full ghcr.io/borodatych/vibedpn-ui:e2e-full
```

```bash
colima ssh -- sh -c 'cd /Volumes/Storage/Projects/VibeCode/VibeDPN && VIBEDPN_TAG=e2e sh tests/e2e/home.sh'
```

В CI его гоняет задача `e2e-home`.

## Что не проверить локально

Сетевую часть (nft, ip rule, WireGuard) — только на Linux-хосте или в E2E-стенде выше. На macOS ядро
colima — Linux, но сеть хоста — это сеть виртуальной машины. Коробку на одном порту, где роутер
провайдера в одном L2 с интерфейсом хоста, не воспроизводит и стенд.
