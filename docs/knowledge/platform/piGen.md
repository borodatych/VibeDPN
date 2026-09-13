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

## [провайдер] Первая настройка Raspberry Pi OS на trixie — cloud-init

**Суть:** Raspberry Pi OS на Debian trixie (образы от 24.11.2025) проводит первую настройку через cloud-init.
С загрузочного раздела FAT32 читаются `meta-data`, `network-config` (сеть) и `user-data` (почти всё остальное: пользователь, ключи, пакеты).
Raspberry Pi Imager 2.0 генерирует эту конфигурацию сам из окна настройки ОС.
Подхватывает ли её собственный образ из `pi-gen`, в статье не сказано — это проверяется сборкой.

## [провайдер] debos: действия рецепта и загрузчик

**Суть (документация пакета `actions`):** в корне рецепта `architecture:`; действия `debootstrap` (`suite`, `mirror`, `components`, `variant`, `keyring-package`/`keyring-file`), `apt` (`packages`), `run` (`chroot`, `command` или `script`), `overlay` (`source`, `destination`), `image-partition` (`imagename`, `imagesize`, `partitiontype: gpt`, `partitions` с `name`/`fs`/`start`/`end`/`flags`, `mountpoints`), `filesystem-deploy` (`setup-fstab`, `setup-kernel-cmdline`).
Своего действия для загрузчика нет: GRUB-EFI или systemd-boot ставятся действием `run` в chroot.
Без `--disable-fakemachine` debos поднимает виртуальную машину fakemachine и требует KVM; с ним — работает прямо на хосте от root.

## [провайдер] cloud-init NoCloud: откуда берётся user-data

**Суть:** NoCloud ищет файловую систему vfat или iso9660 с меткой тома `CIDATA`; в корне обязательны `user-data` и `meta-data`, по желанию `network-config` и `vendor-data`.
Второй путь — командная строка ядра или SMBIOS: `ds=nocloud;s=file:///путь/` (косая черта в конце обязательна) или URL.
Системная настройка — файлы `*.cfg` в `/etc/cloud/cloud.cfg.d/`, они перекрывают `/etc/cloud/cloud.cfg`.
Различается ли регистр метки, документация явно не говорит.

**Источники:** https://docs.cloud-init.io/en/latest/reference/datasources/nocloud.html (NoCloud); https://www.raspberrypi.com/news/cloud-init-on-raspberry-pi-os/ (cloud-init); https://pkg.go.dev/github.com/go-debos/debos/actions (действия debos); https://github.com/go-debos/debos (fakemachine, KVM); https://github.com/RPi-Distro/pi-gen (ветки, методы сборки); https://raw.githubusercontent.com/RPi-Distro/pi-gen/arm64/README.md (переменные, стадии, Docker); https://docs.github.com/en/actions/reference/runners/github-hosted-runners (размеры раннеров).
