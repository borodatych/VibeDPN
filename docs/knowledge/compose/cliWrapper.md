# Обвязка CLI над Compose

## [договорённость] Как `vibedpn up|down|restart` зовут Compose и почему именно так

**Контекст:** Stage 1, чекбокс 3; проверено исполнением на Compose 5.3.1 (colima).
**Суть:** все команды идут через `docker compose --project-directory <каталог коробки>`: `.env`
и `compose.yaml` читаются из него независимо от cwd (проверено: с cwd=/tmp профили из `.env`
коробки подхватились). `up -d --remove-orphans` — после смены роли контейнеры выпавших профилей
удаляются, а не висят. `down` — с `--profile '*'`: без него Compose гасит только сервисы активных
профилей, и контейнер чужого профиля остаётся жить. `restart` двухшаговый: `up -d` применяет
изменения `.env`/compose (пересоздание), но `config.yaml` смонтирован bind-mount'ом и его правка
пересоздание не вызывает — поэтому следом `compose restart`, чтобы контейнеры перечитали конфиг.
`.env` — производная и пересобирается перед `up`/`restart` из `config.yaml` (`render_env` +
сохранённые `VIBEDPN_TAG`, `MYST_TAG`, `ADGUARD_TAG`): правка конфига руками работает без
`init --force`. `ps --format json` отдаёт объект на строку (поля `Service`, `State`, `Health`,
`Status`); парсер принимает и массив на случай старых версий. Preflight — `docker version
--format {{.Server.Version}}`: «permission denied» → перелогиниться после добавления в группу
docker, «cannot connect» → демон не запущен.
**Источники:** https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/
(`.env` из project directory), https://docs.docker.com/compose/how-tos/profiles/ (`--profile "*"`),
https://docs.docker.com/reference/cli/docker/compose/up/ (`--remove-orphans`),
https://docs.docker.com/reference/cli/docker/compose/ps/ (`--format json`).
