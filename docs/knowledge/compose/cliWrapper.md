# Обвязка CLI над Compose

## [договорённость] Как `vibedpn up|down|restart` зовут Compose и почему именно так

**Контекст:** Stage 1, чекбокс 3; проверено исполнением на Compose 5.3.1 (colima).
**Суть:** все команды идут через `docker compose --project-directory <каталог коробки>`: `.env`
и `compose.yaml` читаются из него независимо от cwd (проверено: с cwd=/tmp профили из `.env`
коробки подхватились). **`--remove-orphans` не убирает контейнеры выключенных профилей** — для
Compose 5.3.1 «сирота» это сервис, которого нет в файле вообще, а сервис отключённого профиля он
знает и не трогает (проверено: после смены `COMPOSE_PROFILES=dns` на пустой `up -d
--remove-orphans` оставил `adguard` работать). Поэтому `up`/`restart` сначала считают разность
`config --services` с `--profile '*'` и без и гасят её через `--profile '*' rm --stop --force
<сервисы>` — `rm` без контейнеров возвращает 0. `down` — с `--profile '*'`: без него Compose
гасит только сервисы активных профилей.
**Владелец файлов:** `install.sh` и `init` работают под sudo, поэтому `init` отдаёт `config.yaml`,
`.env` и `config.yaml.bak` вызвавшему пользователю по `SUDO_UID`/`SUDO_GID` — иначе `up`/`restart`
без sudo падали на `O_TRUNC` root-овского `.env`, а мануал обещал работу без sudo ради группы
`docker`. Переписать свой файл можно и в каталоге без права записи. `secrets/` остаётся root 700.
**Тег образов:** `latest` публикуется только с `main`; коробка с `VIBEDPN_BRANCH=next` и
`VIBEDPN_TAG=latest` получала «manifest unknown», и Compose из-за `build:` молча собирал три
образа на месте (на Pi — десятки минут). `init` выводит тег из `git symbolic-ref --short HEAD`
(`main` → `latest`, иначе имя ветки с заменой недопустимых символов на `-`, как у
docker/metadata-action); записанный тег сильнее. `restart` двухшаговый: `up -d` применяет
изменения `.env`/compose (пересоздание), но `config.yaml` смонтирован bind-mount'ом и его правка
пересоздание не вызывает — поэтому следом `compose restart`, чтобы контейнеры перечитали конфиг.
`.env` — производная и пересобирается перед `up`/`restart` из `config.yaml` (`render_env` +
сохранённые `VIBEDPN_TAG`, `MYST_TAG`, `ADGUARD_TAG`): правка конфига руками работает без
`init --force`. `ps --format json` отдаёт объект на строку (поля `Service`, `State`, `Health`,
`Status`); парсер принимает и массив на случай старых версий. Preflight — `docker version
--format {{.Server.Version}}`: «permission denied» → перелогиниться после добавления в группу
docker, «cannot connect» → демон не запущен.
Preflight матчит не прозу CLI, а ошибку dial: Docker 29 пишет «failed to connect to the docker
API … dial unix …: connect: no such file or directory», старые — «Cannot connect …»; на права
указывает «permission denied» в обеих версиях.
**Источники:** https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/
(`.env` из project directory), https://docs.docker.com/compose/how-tos/profiles/ (`--profile "*"`),
https://docs.docker.com/reference/cli/docker/compose/up/ (`--remove-orphans`),
https://docs.docker.com/reference/cli/docker/compose/rm/ , https://docs.docker.com/reference/cli/docker/compose/ps/
(`--format json`), https://github.com/docker/metadata-action (`type=ref,event=branch`),
https://www.sudo.ws/docs/man/sudo.man/ (`SUDO_UID`, `SUDO_GID`, `env_reset`).
