# GitHub Actions и GHCR

## [провайдер] Версии actions, раннеры, публикация в GHCR

**Контекст:** `.github/workflows/ci.yml` Stage 0.
**Суть (2026-09-11):** `actions/checkout@v7`, `actions/setup-node@v7`, `actions/setup-python@v7`,
`docker/setup-qemu-action@v4`, `docker/setup-buildx-action@v4`, `docker/login-action@v4`,
`docker/metadata-action@v6`, `docker/build-push-action@v7`. У `astral-sh/setup-uv` **нет плавающего
мажорного тега**: `@v10` не резолвится, только `@v10.1.0` или SHA. `ubuntu-latest` = 24.04;
arm64-раннеры `ubuntu-24.04-arm` бесплатны в публичных репо (GA с 2025-08-07) — вариант вместо QEMU;
`ubuntu-22.04` уходит с 2026-09-17. Для push в GHCR хватает `permissions: contents: read,
packages: write` (`attestations`/`id-token` — только вместе с шагом аттестации); логин
`registry: ghcr.io`, `username: ${{ github.actor }}`, `password: ${{ secrets.GITHUB_TOKEN }}`.
Имя образа `ghcr.io/NAMESPACE/IMAGE`, namespace в нижнем регистре (`${GITHUB_REPOSITORY_OWNER,,}`).
Кэш buildx `type=gha` со `scope` на образ. actionlint 1.7.12: в CI ставится скриптом
`download-actionlint.bash <версия>`, локально `brew install actionlint`. Ruff 0.16 переписал набор
правил по умолчанию — держим явный `select` и `ruff>=0.16.7,<0.17`.
**Источники:** https://github.com/actions/checkout/releases , https://github.com/actions/setup-node/releases ,
https://github.com/astral-sh/setup-uv/releases , https://github.com/docker/setup-qemu-action/releases ,
https://github.com/docker/setup-buildx-action/releases , https://github.com/docker/login-action ,
https://github.com/docker/metadata-action , https://github.com/docker/build-push-action ,
https://docs.docker.com/build/ci/github-actions/multi-platform/ ,
https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images ,
https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry ,
https://github.com/actions/runner-images , https://github.com/actions/runner-images/issues/14254 ,
https://github.blog/changelog/2025-08-07-arm64-hosted-runners-for-public-repositories-are-now-generally-available/ ,
https://github.com/rhysd/actionlint/blob/main/docs/usage.md , https://github.com/astral-sh/ruff/releases/tag/0.16.0 .

## [баг] Тест в контейнере на раннере: git «dubious ownership» и `&&` под `set -e`

**Контекст:** задача `install` гоняет `install.sh` внутри `debian:*-slim` с bind-mount чекаута
`/src`; локально в colima проходила, в GitHub падала.
**Суть:** на раннере владелец `/src` — uid раннера, внутри контейнера мы root, и git отказывается
клонировать: «detected dubious ownership», причём просит `safe.directory /src/.git` (путь до
`.git`, не до каталога). В одноразовом контейнере проще `git config --global --add
safe.directory "*"`. Вторая грабля скрыла первую: `git clone … && git checkout …` под `bash -e`
не останавливает скрипт — в AND-списках `set -e` не действует ни на одну команду, кроме
последней, — и тест ушёл дальше до `fatal: repository '/tmp/repo' does not exist` в install.sh.
**Применение:** в скриптах для CI — команды отдельными строками, `&&` только там, где короткое
замыкание и нужно; клон чужого чекаута — с `safe.directory`.
**Источники:** https://git-scm.com/docs/git-config#Documentation/git-config.txt-safedirectory ,
https://www.gnu.org/software/bash/manual/html_node/The-Set-Builtin.html (поведение `-e` в списках).
