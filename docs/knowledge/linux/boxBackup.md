# Резервная копия и обновление коробки: факты платформы

## [провайдер] tarfile без фильтра распаковки в Debian bookworm

**Контекст:** Stage 11, `vibedpn backup|restore|update`, 2026-09-13.

**Суть (исполнением, `debian:bookworm-slim` и `debian:trixie-slim`, пакет `python3`):**
bookworm — Python `3.11.2`, `tarfile.data_filter` и `tarfile.tar_filter` отсутствуют.
trixie — Python `3.13.5`, `tarfile.data_filter` есть.
`install.sh` принимает Python от 3.11, значит защита распаковки не может держаться на фильтре: члены архива проверяются кодом (абсолютные пути, `..`, ссылки наружу, устройства), фильтр `tar` добавляется, где он есть.
Фильтр `data` не годится и там, где есть: он отбрасывает владельца файлов, а каталог Postgres панели должен остаться за пользователем контейнера — распаковка идёт с `numeric_owner=True`.

## [провайдер] `docker compose pull --ignore-buildable`

**Суть (исполнением, Docker Compose v5.1.4 на colima VM):** `docker compose pull --help` — `--ignore-buildable  Ignore images that can be built`, `--ignore-pull-failures`, `--policy string  Apply pull policy ("missing"|"always")`.
У сервисов коробки с `build:` (`core`, `wg`, `dnsmasq`, `hostapd` и другие) `update` тянет опубликованные образы и не пытается собирать чужие.

## [провайдер] Таймер systemd для автообновления

**Суть (из man):** `OnCalendar=` — таймер по календарным выражениям; `RandomizedDelaySec=` — случайная задержка от 0 до значения; `Persistent=true` — время последнего запуска хранится на диске и пропущенный запуск догоняется после выключения; `Unit=` по умолчанию — сервис с тем же именем, что у таймера.

## [провайдер] AdGuard Home не от root поднимает порт 53

**Контекст:** Stage 11, «DNS AdGuard через аплинк в `full`»: вариант метить трафик AdGuard по UID (`meta skuid`) требует, чтобы он жил под своим пользователем.

**Суть (исполнением, `adguard/adguardhome:v0.107.79`, `--network host --user 7753:7753 --cap-add NET_BIND_SERVICE`, конфиг и рабочий каталог принадлежат 7753):**
`dnsproxy: listening to udp addr=127.0.0.77:53` и `listening to tcp addr=127.0.0.77:53`, контейнер работает.
В `/proc/<pid>/status`: `Uid: 7753`, `CapEff: 0000000000000400` — ровно `NET_BIND_SERVICE`.
**Грабля опыта:** на colima VM `127.0.0.1:53` и `192.168.5.1:53` держит dnsmasq самой colima — первый опыт на `127.0.0.1` упал на TCP `address already in use`, это не отказ в правах.

**Источники:** https://man7.org/linux/man-pages/man5/systemd.timer.5.html ; https://docs.python.org/3/library/tarfile.html#extraction-filters ; https://docs.docker.com/reference/cli/docker/compose/pull/


## Самообновляющийся скрипт и bash (проверено 2026-09-18)

`install.sh` обновляет собственный файл, а bash читает скрипт по смещению и после возврата из
`main` дочитывает файл заново. Опыт на минимальном скрипте: переписал себя на месте (`> "$0"`) —
после `main` bash выполняет мусор из нового текста (`хвост-мусор-7: command not found`);
то же тело в группе `{ main "$@"; exit 0; }` завершается чисто, потому что группа разобрана
целиком до запуска `main`.

У нас не стреляло по причине, которую стоит знать: git заменяет файл **переименованием**, и у
запущенного bash остаётся открытым старый inode — проверено отдельным опытом с `mv`.
Отсюда же практическое следствие для выкладки: правка `install.sh` доезжает до коробки со
**следующего** прогона, потому что текущий работает со старого файла.

`vibedpn update` проверен исполнением там же: 34 с на круг, а при недоступном github падает
с «the box keeps running the previous version» и ничего не ломает.
