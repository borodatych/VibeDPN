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

**Источники:** https://docs.cloud-init.io/en/latest/reference/datasources/nocloud.html (NoCloud); https://www.raspberrypi.com/news/cloud-init-on-raspberry-pi-os/ (cloud-init); https://pkg.go.dev/github.com/go-debos/debos/actions (действия debos); https://github.com/go-debos/debos (fakemachine, KVM); https://github.com/RPi-Distro/pi-gen (ветки, методы сборки); https://raw.githubusercontent.com/RPi-Distro/pi-gen/arm64/README.md (переменные, стадии, Docker); https://docs.github.com/en/actions/reference/runners/github-hosted-runners (размеры раннеров).
