# Локальная разработка (macOS)

Что нужно, чтобы прогнать все проверки проекта на машине разработчика, и как это проверяется.

## Инструменты

| Инструмент | Зачем | Установка |
|---|---|---|
| `uv` | Python 3.12, зависимости `core/`, запуск ruff/mypy/pytest | `brew install uv`; интерпретаторы и кэш uv у владельца живут на томе Storage (`UV_PYTHON_INSTALL_DIR`, `UV_CACHE_DIR` в `~/.zshrc`) |
| Docker + Compose v2 + buildx | `compose config`, сборка образов | colima (`brew install colima docker docker-compose docker-buildx`), `colima start`; образы собираются под arm64 хоста, amd64 — в CI. См. «Colima» ниже |
| `actionlint` | проверка `.github/workflows` | `brew install actionlint` |
| `shellcheck` | проверка shell-скриптов | `brew install shellcheck` |

## Порядок

1. `cd core && uv sync --locked` — ставит Python 3.12 и зависимости в `core/.venv`.
2. Проверки ядра: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`.
3. Compose: из корня `docker compose --profile '*' config -q` — валидирует файл со всеми профилями
   без `.env` (дефолты в `compose.yaml` не открывают ничего наружу).
4. Скрипты и workflow: `git ls-files -z '*.sh' | xargs -0 shellcheck` и `actionlint`.
5. Образы: `docker compose --profile '*' build` — собирает `core`, `wg`, `ui` локально.

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

## Что не проверить локально

Сетевую часть (nft, ip rule, WireGuard) — только на Linux-хосте или в e2e-стенде `tests/e2e`
(Stage 4). На macOS ядро colima — Linux, но сеть хоста — это сеть виртуальной машины.
