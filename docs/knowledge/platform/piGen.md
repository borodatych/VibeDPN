# pi-gen: сборка образа Raspberry Pi со своей стадией

## [провайдер] Ветки, пользователь, своя стадия, сборка в Docker

**Контекст:** Stage 12, готовый образ для Raspberry Pi с предустановленным VibeDPN, 2026-09-13.

**Ветки:** 32-битные образы (armhf) собираются из `master`, 64-битные (arm64) — из ветки `arm64`; релиз по умолчанию — `trixie` (`RELEASE`).

**Пользователь и доступ:**
`FIRST_USER_NAME` (по умолчанию `pi`) — «This user only exists during the image creation process»; `FIRST_USER_PASS` не задан — учётная запись заблокирована.
`DISABLE_FIRST_BOOT_USER_RENAME=0` — при первой загрузке пользователя переименовывают.
`ENABLE_SSH=1` включает sshd, `PUBKEY_SSH_FIRST_USER` кладёт ключ в `authorized_keys`.
Пароль в образ зашивать нельзя: образ публикуется, пароль стал бы общим.

**Своя стадия:** каталог с `prerun.sh` (копирует сборку предыдущей стадии), `00-packages` (пакеты через пробел), `00-run.sh` (на хосте сборки), `00-run-chroot.sh` (внутри образа), `files/`, `EXPORT_IMAGE` (создать образ после стадии); порядок задаёт `STAGE_LIST`.
Образ Lite — стадии 0–2; остальным ставятся `SKIP`, стадиям 4 и 5 ещё `SKIP_IMAGES`.

**Сборка в Docker:** `build-docker.sh` запускает контейнер с `--privileged` (binfmt, loop-устройства); для чужой архитектуры нужны `binfmt-support` и `qemu-user-static`; места — «tens of gigabytes»; `CONTINUE=1` продолжает упавшую сборку, `PRESERVE_CONTAINER=1` оставляет контейнер.

**Хост разработки (исполнением, colima VM aarch64):** `/dev/loop-control`, `/dev/loop0` есть, `losetup -f` отдаёт `/dev/loop0`, `docker run --privileged` видит `/dev/loop-control`; драйвер хранилища `overlayfs`; свободно 16 ГБ — на полную сборку может не хватить.
Раннеры GitHub `ubuntu-24.04` и `ubuntu-24.04-arm`: 4 vCPU, 16 ГБ памяти, 14 ГБ диска.

## [провайдер] Как pi-gen выполняет подстадии (по исходникам, коммит `86919dae` ветки `arm64`)

**Суть (чтением `build.sh` и `stage2` на прибитом коммите, 2026-09-14):**
Подстадия — каталог `NN-имя` внутри стадии; в нём `NN-packages`, `NN-packages-nr` (без рекомендаций), `NN-debconf`, `NN-patches`, `NN-run.sh`, `NN-run-chroot.sh`, `files/`.
`NN-run.sh` запускается на хосте сборки, только если файл исполняемый; неисполняемый пропускается с записью `Skip ... (not executable)` — бит исполнения должен жить в git.
`NN-run-chroot.sh` отдаётся в chroot через stdin (`on_chroot < NN-run-chroot.sh`): переменные сборки внутри не раскрываются, значения нужно положить в образ файлом.
`build.sh` подключает `config` через `source config` без `set -a`: свои переменные в `config` пишутся как `export ИМЯ=…`, иначе `NN-run.sh` их не увидит; `build-docker.sh` передаёт в контейнер только файл `config`, не окружение хоста.
`stage2/EXPORT_IMAGE` задаёт `IMG_SUFFIX="-lite"`; `prerun.sh` — `copy_previous`, если корня стадии ещё нет.
В `stage2` уже есть подстадия `04-cloud-init`: образ Lite несёт cloud-init, и настройка из Raspberry Pi Imager в собственном образе работает тем же путём.

## [провайдер] Первая настройка Raspberry Pi OS на trixie — cloud-init

**Суть:** Raspberry Pi OS на Debian trixie (образы от 24.11.2025) проводит первую настройку через cloud-init.
С загрузочного раздела FAT32 читаются `meta-data`, `network-config` (сеть) и `user-data` (почти всё остальное: пользователь, ключи, пакеты).
Raspberry Pi Imager 2.0 генерирует эту конфигурацию сам из окна настройки ОС.
Подхватывает ли её собственный образ из `pi-gen`, в статье не сказано — это проверяется сборкой.

## [провайдер] debos: действия рецепта и загрузчик

**Суть (документация пакета `actions`):** в корне рецепта `architecture:`; действия `debootstrap` (`suite`, `mirror`, `components`, `variant`, `keyring-package`/`keyring-file`), `apt` (`packages`), `run` (`chroot`, `command` или `script`), `overlay` (`source`, `destination`), `image-partition` (`imagename`, `imagesize`, `partitiontype: gpt`, `partitions` с `name`/`fs`/`start`/`end`/`flags`, `mountpoints`), `filesystem-deploy` (`setup-fstab`, `setup-kernel-cmdline`).
Своего действия для загрузчика нет: GRUB-EFI или systemd-boot ставятся действием `run` в chroot.
Без `--disable-fakemachine` debos поднимает виртуальную машину fakemachine и требует KVM; с ним — работает прямо на хосте от root.

## [опыт] debos без fakemachine не строит корень на томе Mac

**Суть (исполнением, `godebos/debos` arm64 на colima VM, 2026-09-14):** с `--disable-fakemachine` debos кладёт корень образа в `.debos-<число>/root` рядом с рецептом.
Рецепт на смонтированном томе Mac (virtiofs) — `debootstrap` падает через 110 с: `tar: ./usr/lib/apt/planners/dump: Cannot open: Permission denied`, `Action debootstrap failed`.
Сборка идёт из копии рецептов на собственном диске VM (`/var/tmp/vibedpn-os`); оставшийся каталог `.debos-*` принадлежит root и удаляется через `sudo`.

## [опыт] debos в Docker без fakemachine не проходит дальше debootstrap

**Суть (исполнением, colima VM, рецепты на диске VM, 2026-09-14):** `debootstrap` отработал (`Base system installed successfully`), следующий шаг `apt clean` debos выполняет через `systemd-nspawn`, и внутри контейнера он падает:
`Failed to stat /dev/disk: No such file or directory`, `Attempted to remove disk file system under "/run/systemd/nspawn/propagate/debos-…", and we can't allow that.`
С fakemachine нужен KVM, а у VM на Mac его нет. Локально UEFI-образ не собрать; путь — раннер `ubuntu-24.04` с KVM (workflow `os-images`).

## [провайдер] cloud-init NoCloud: откуда берётся user-data

**Суть:** NoCloud ищет файловую систему vfat или iso9660 с меткой тома `CIDATA`; в корне обязательны `user-data` и `meta-data`, по желанию `network-config` и `vendor-data`.
Второй путь — командная строка ядра или SMBIOS: `ds=nocloud;s=file:///путь/` (косая черта в конце обязательна) или URL.
Системная настройка — файлы `*.cfg` в `/etc/cloud/cloud.cfg.d/`, они перекрывают `/etc/cloud/cloud.cfg`.
Различается ли регистр метки, документация явно не говорит.

## [опыт] fakemachine отдаёт виртуальной машине только каталог рецепта и рабочий каталог

**Суть (прогон `os-images` 35373779695 на теге v0.1.0, 2026-09-18; исходники debos `cmd/debos/debos.go`):** debos с fakemachine делает в VM ровно два тома — `RecipeDir` (каталог файла рецепта) и `Artifactdir` (`--artifactdir`, по умолчанию текущий каталог), по тем же путям, что на хосте.
Рецепт `images/os/debos/vibedpn.yaml` читает `../common` и `../../../install.sh`, а workflow запускал debos из `images/os/debos` — оба пути оказались вне томов, и обе UEFI-задачи упали на проверке `overlay`: `stat /recipes/images/os/common: no such file or directory`.
Лечится рабочим каталогом в корне репозитория: тогда весь репозиторий и есть каталог артефактов, а образ появляется в его корне.
Заодно про ресурсы VM (`fakemachine/machine.go`): память по умолчанию 2 ГБ, 2 CPU, `/scratch` — tmpfs на 95 % памяти VM, если не задан `--scratchsize`; с ним debos создаёт разрежённый файл `fake-scratch.img.*` в рабочем каталоге и отдаёт его VM диском.
Корень с Docker Engine в 2 ГБ tmpfs не помещается, поэтому сборка идёт с `--memory 4GB --scratchsize 8GB`.

## [опыт] `/tmp` корня образа невидим для `run` с `chroot: true`

**Суть (сборка на N100, 2026-09-20; исходники systemd `src/nspawn/nspawn.c`, `nspawn-mount.c`):** действие `overlay` положило `images/os/common` в `/tmp/vibedpn-image` корня, а следующее `run chroot: true` ответило `cp: cannot stat '/tmp/vibedpn-image/99-vibedpn.cfg'`.
Команды в chroot debos выполняет через `systemd-nspawn`, а тот по умолчанию (`arg_mount_settings` содержит `MOUNT_APPLY_TMPFS_TMP`) монтирует поверх `/tmp` контейнера пустой tmpfs — файлы корня под ним не видны.
`/var/tmp` в таблице монтирований nspawn нет, поэтому каталог сборки образа — `/var/tmp/vibedpn-image` во всех трёх местах: `provision.sh`, рецепт debos и стадия pi-gen (там `on_chroot` — обычный chroot, но каталог один на оба конвейера).

## [провайдер] Эмуляция arm64 на amd64-хосте для pi-gen: `qemu-user` в trixie статический

**Суть (Debian 13 на коробке N100, 2026-09-20):** пакет `qemu-user-static` в trixie — переходный («Now this functionality is provided by qemu-user package»), бинарники `qemu-user` собраны как static-pie (`file /usr/bin/qemu-aarch64`).
`qemu-user-binfmt` регистрирует `qemu-aarch64` через `/usr/lib/binfmt.d/` с интерпретатором `/usr/libexec/qemu-binfmt/aarch64-binfmt-P` и флагами `POF` — `F` держит интерпретатор открытым, и он работает внутри chroot и контейнеров.
`build-docker.sh` pi-gen на не-arm хосте требует `qemu-aarch64` в `PATH` (иначе «please install qemu-user-binfmt») и, не найдя своего интерпретатора в записях `qemu-aarch64*`, регистрирует ещё `qemu-aarch64-rpi` с флагом `F`.
Проверка после установки: `docker run --rm --platform linux/arm64 debian:trixie-slim uname -m` → `aarch64`.
Пакет весит около 460 МБ на диске (эмуляторы всех архитектур).
Цена эмуляции: полная сборка образа Raspberry Pi на N100 (4 ядра, ещё две сборки рядом) заняла 65 минут против 11 минут нативно на раннере `ubuntu-24.04-arm`; результат тот же — `image_<дата>-vibedpn-arm64.img.xz` на 706 МБ.

## [опыт] pi-gen экспортирует и голый образ Lite, если stage2 не помечен `SKIP_IMAGES`

**Суть (прогон 35373779695):** `stage2/EXPORT_IMAGE` есть в самом pi-gen, поэтому вместе с `image_…-vibedpn-arm64.img.xz` (706 МБ) в `deploy/` появился `image_…-vibedpn-lite.img.xz` (578 МБ) без VibeDPN — семь лишних минут экспорта и вдвое больший артефакт.
`build.sh` теперь создаёт `work/stage2/SKIP_IMAGES`: `build.sh` pi-gen не добавляет такую стадию в `EXPORT_DIRS`.
`ENABLE_CLOUD_INIT` менять не нужно — по умолчанию `1`, и в журнале прогона стадия `stage2/04-cloud-init` ставит `cloud-init` и `rpi-cloud-init-mods`.

## [провайдер] Что внутри `godebos/debos` (2026-09-20)

**Суть (исполнением, `docker run --entrypoint sh godebos/debos`):** Debian trixie, `linux-image-amd64` 6.12.63 — ядро для fakemachine, `qemu-system-x86`, `qemu-user` и `qemu-user-binfmt` (trixie, статические), `binfmt-support`; `/var/lib/binfmts` пуст, регистрация идёт через `/usr/lib/binfmt.d/`.
Значит для arm64-рецепта хосту эмуляция не нужна: у VM своё ядро, и регистрирует эмуляторы она сама из файлов контейнера.

## [опыт] Что образ debos получает от машины сборки: имя хоста

**Суть (разбор собранного `vibedpn-amd64.img` на N100, 2026-09-20; исходники debootstrap, `functions`, `setup_etc`):** в `/etc/hostname` образа оказалось `fakemachine` — debootstrap делает `conditional_cp /etc/hostname "$TARGET"`, то есть копирует имя хоста сборки (виртуальной машины fakemachine) в корень.
У pi-gen имя задаёт `TARGET_HOSTNAME`; в рецепте debos имя пишется явно действием `run` (`/etc/hostname` и строка `127.0.1.1` в `/etc/hosts`), а `hostname:` в `user-data` cloud-init его при желании перекрывает.

## [опыт] Образ debos без сетевого стека загружается без адреса: cloud-init нужен ifupdown

**Суть (тест `tests/os/uefiBoot.sh` на N100, 2026-09-20):** первый собранный `vibedpn-amd64.img` загрузился (cloud-init завёл пользователя, ключи хоста сделал), но ssh не ответил за 300 с.
Разбор образа: `/etc/network` нет, netplan нет, `systemd-networkd.service` есть в `systemd`, но не включён — cloud-init записать конфигурацию сети некому применить.
Debian-путь тот же, что у коробки владельца: `ifupdown` (первый renderer cloud-init, `eni`, пишет `/etc/network/interfaces.d/50-cloud-init`) и `dhcpcd-base` как DHCP-клиент; с ними ssh отвечает через 15 с после старта VM.
Debian minbase не тянет ни того, ни другого, а действие `apt` debos не ставит Recommends — пакеты перечислены в рецепте явно.
Пересборка образа amd64 на N100 (`--cpus 2 --memory 4GB --scratchsize 8GB`): 5 минут, файл 6 ГБ разрежённый, 1.3 ГБ на диске.

## [опыт] minbase без `e2fsprogs` и `procps`: cloud-init не растягивает корень, CLI не найдёт `ps`

**Суть (`tests/os/uefiBoot.sh` на N100, 2026-09-20):** во втором образе сеть и ssh поднялись, но `cloud-init status` кончился `error`: модуль `resizefs` не нашёл `resize2fs` — `debootstrap --variant=minbase` не ставит `e2fsprogs`, а рецепт его не просил.
Без `cloud-guest-utils` (`growpart`) нет и растяжения раздела: образ в 6 ГБ на диске в 128 ГБ так и остался бы шестью гигабайтами.
Заодно из того, что есть в обычной установке Debian и нужно коробке: `procps` (`ps` зовёт CLI), `dosfstools` (fsck раздела `CIDATA`), `gdisk` (GPT для `growpart`), `nano`, `less`, `iputils-ping`.
Тест теперь наращивает копию образа на 2 ГБ и требует корень больше 6.5 ГБ, а после мастера прогоняет `vibedpn init --role vps` и `vibedpn doctor` — так ловится любой инструмент, которого в образе нет.

**Источники:** https://docs.cloud-init.io/en/latest/reference/datasources/nocloud.html (NoCloud); https://www.raspberrypi.com/news/cloud-init-on-raspberry-pi-os/ (cloud-init); https://pkg.go.dev/github.com/go-debos/debos/actions (действия debos); https://github.com/go-debos/debos (fakemachine, KVM); https://github.com/RPi-Distro/pi-gen (ветки, методы сборки); https://raw.githubusercontent.com/RPi-Distro/pi-gen/arm64/README.md (переменные, стадии, Docker); https://docs.github.com/en/actions/reference/runners/github-hosted-runners (размеры раннеров); https://github.com/go-debos/debos/blob/master/cmd/debos/debos.go и https://github.com/go-debos/fakemachine/blob/master/machine.go (тома, память, scratch); https://github.com/systemd/systemd/blob/main/src/nspawn/nspawn-mount.c (tmpfs на `/tmp`); https://packages.debian.org/trixie/qemu-user-static (переходный пакет); https://salsa.debian.org/installer-team/debootstrap/-/blob/master/functions (`setup_etc`, копия `/etc/hostname`).
