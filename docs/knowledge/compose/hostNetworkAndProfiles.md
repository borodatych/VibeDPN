# Docker Compose: host network, профили, статические IP

## [архитектура] Что нельзя сочетать с `network_mode: host`

**Контекст:** `core`, `ui`, `wg-server`, `adguard` живут в сети хоста.
**Суть:** при `network_mode` нельзя указывать `networks` (файл отклоняется) и `ports` (ошибка в
рантайме); sysctl `net.*` — только для контейнеров со своим сетевым пространством, с `--network=host`
они запрещены (значит `ip_forward` для wg-server ставит хост, а не compose); `links` с host —
ошибка движка. Статический IP требует пользовательской сети с `ipam.config[].subnet`
(`networks.<net>.ipv4_address`); драйвер по умолчанию — bridge (из движка, в спеке не написано).
`depends_on` на сервис неактивного профиля — ошибка конфигурации. Профили включаются
`COMPOSE_PROFILES=a,b` или повторяемым `--profile`; `--profile '*'` — все (так гоняем `config` в CI).
Канонический файл — `compose.yaml` (kickoff называл `docker-compose.yml`, оба поддерживаются,
при обоих побеждает `compose.yaml`); ключ `version:` устарел и даёт предупреждение; `name:` задаёт
имя проекта. Compose 5.5.1 (2026-09-03).
**Источники:** https://docs.docker.com/reference/compose-file/services/ ,
https://docs.docker.com/reference/compose-file/networks/ ,
https://docs.docker.com/reference/compose-file/profiles/ ,
https://docs.docker.com/reference/cli/docker/container/run/#sysctl ,
https://docs.docker.com/compose/intro/compose-application-model/ ,
https://docs.docker.com/reference/compose-file/version-and-name/ ,
https://api.github.com/repos/docker/compose/releases/latest .

## [провайдер] Какие файлы Compose читает: override, `--project-directory`, явные `-f`

**Контекст:** Stage 10, сервисы consumer на каждую страну в генерируемом файле рядом с `compose.yaml`, 2026-09-14.

**Суть (исполнением, Docker Compose v5.1.4 на colima VM, запуск из другого каталога):**
`docker compose --project-directory D config --services` без `-f` — `base` и `from-override`: `compose.override.yaml` из каталога проекта подхватывается сам.
`-f D/compose.yaml -f D/compose.countries.yaml --profile "*"` — `from-countries` и `base`: читаются только перечисленные файлы, `compose.override.yaml` уже нет.
`-f` на отсутствующий файл — ошибка `open …/missing.yaml: no such file or directory`.
Документация: «By default, Compose reads two files, a `compose.yaml` and an optional `compose.override.yaml` file»; с `-f` — только указанные, в указанном порядке.

**Как применять:** свой генерируемый файл передаётся явным `-f`, и тогда `compose.override.yaml` владельца нужно передать тоже, если он есть; генерируемый файл должен существовать всегда.

**Источник:** https://docs.docker.com/compose/how-tos/multiple-compose-files/merge/
