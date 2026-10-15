# Диск для загрузок: lsblk, юнит монтирования, exfat и ntfs

## [torrents] Как коробка видит и монтирует диск

**Контекст:** торрент-клиент (`torrents.storage`) качает на внешний диск, выбранный по UUID файловой системы. Диск монтирует хост (`vibedpn up`), не ядро: контейнер ядра не видит блочных устройств хоста. Проверено 15.10.2026 на Ubuntu 24.04 (ядро 6.8, systemd 255, util-linux 2.39) в виртуальной машине colima с петлевыми образами ext4, exfat и ntfs.

**Суть:**
- `lsblk -J -b -o NAME,PATH,UUID,LABEL,FSTYPE,SIZE,TYPE,MOUNTPOINTS` отдаёт дерево `blockdevices` с вложенными `children`; размеры в байтах (`-b`), точки монтирования массивом `mountpoints`.
  Пустой список lsblk 2.39 пишет как `[null]`, а 2.41 как `[]` — разбор принимает обе формы. Раздел USB-диска — `type: part`, сам диск — `disk`; `loop` в список не берётся.
  Снимок формата лежит в `core/tests/fixtures/lsblk.json`.
- Тип файловой системы lsblk печатает по blkid: `ext4`, `exfat`, `ntfs` (не `ntfs3`), `vfat`. Берутся только эти три; системный диск (корень, `/boot`, `/home`…) не предлагается.
- Диск монтирует родной юнит `srv-vibedpn-usb.mount`: имя юнита обязано совпадать с экранированным путём `Where=` (`/srv/vibedpn/usb` → `srv-vibedpn-usb.mount`). В `Options=` стоит `nofail`: по документации systemd такой юнит не получает `Before=local-fs.target`, поэтому без диска загрузка не останавливается. `WantedBy=multi-user.target`.
  `What=/dev/disk/by-uuid/<uuid>`: ссылка есть и у петлевого устройства. Отсутствующий диск: `systemctl start` отвечает `A dependency job ... failed` и возвращает ошибку, ничего не зависает (проверено).
- Тип и параметры: `ext4` — `noatime,nofail`; `exfat` — `+ uid=7756,gid=7756,umask=002`; `ntfs` — тип `ntfs3` (ядерный драйвер) с теми же `uid`, `gid`, `umask`.
  - exfat проверено: ядро приняло `uid`, `gid`, `umask` и показало `fmask=0002,dmask=0002`; файлы принадлежат 7756.
  - ntfs3 проверено: `uid`, `gid`, `umask` приняты. Каталог, который создал root, принадлежит root (`drwxr-xr-x root root`), но `chown` и `chmod` на томе работают, и после `chown 7756:7756` пользователь 7756 пишет в него (`setpriv --reuid=7756`). Поэтому хост создаёт папки и отдаёт их клиенту, а не полагается на параметры монтирования.
  - ext4 хранит владельцев сам: хост делает `chown 7756:7756` на `complete` и `incomplete`.
- Docker стартует после диска (не проверено перезагрузкой): drop-in `/etc/systemd/system/docker.service.d/vibedpn-storage.conf` с `Wants=` и `After=` юнита (не `Requires=`: нет диска — Docker всё равно стартует).
  Источник bind-каталога должен существовать: в `compose.yaml` стоит `create_host_path: false`, и без диска контейнер не стартует, а не пишет на системный диск. `vibedpn up` в этом случае сам держит профиль `torrents` выключенным и говорит об этом.
- Ядерные драйверы: в `bcm2711_defconfig` ветки ядра Raspberry Pi `rpi-6.12.y` стоит `CONFIG_EXFAT_FS=m` и `CONFIG_NTFS3_FS=m`.
  Конфиги ядер Debian 12 и 13 не проверены (salsa.debian.org не отдаёт сырые файлы), на настоящей плате и на Debian монтирование не пробовали.
- Пакеты `exfatprogs` (в списке пакетов Debian есть bookworm и trixie) и `ntfs-3g` (в нём есть `ntfsfix`) ставит `install.sh` для починки томов; для самого монтирования они не нужны, это делает ядро.
- Для ntfs3 документация ядра описывает `force` как монтирование тома, помеченного «грязным», и не рекомендует его; юнит эту опцию не ставит. Что будет с «грязным» томом без неё, не проверялось.

**Не проверено:** настоящий USB-диск; поведение юнита при перезагрузке с подключённым и отключённым диском; ядра Debian; запись большого объёма.

**Источники:**
- https://man7.org/linux/man-pages/man5/systemd.mount.5.html (имя юнита, `Where=` создаётся, `nofail` в `Options=` убирает `Before=local-fs.target`)
- https://man7.org/linux/man-pages/man8/lsblk.8.html (`--json`, `--bytes`, `MOUNTPOINTS`)
- https://docs.kernel.org/filesystems/ntfs3.html и https://raw.githubusercontent.com/torvalds/linux/master/Documentation/filesystems/ntfs3.rst (`uid`, `gid`, `umask`, `dmask`, `fmask`, `force`)
- https://raw.githubusercontent.com/torvalds/linux/master/fs/exfat/super.c (параметры монтирования exfat: `uid`, `gid`, `umask`, `dmask`, `fmask`)
- https://packages.debian.org/trixie/exfatprogs и https://packages.debian.org/trixie/ntfs-3g (пакеты; в списке файлов ntfs-3g есть `ntfsfix`)
- https://raw.githubusercontent.com/raspberrypi/linux/rpi-6.12.y/arch/arm64/configs/bcm2711_defconfig
