# ГОТОВЫЕ ОБРАЗЫ ОС С VIBEDPN

Как получить диск, с которого коробка сразу загружается с установленным VibeDPN.

---

## 1. Какие образы есть

| Образ | Железо | Чем собирается |
|---|---|---|
| `vibedpn-arm64.img.xz` (Raspberry Pi) | Raspberry Pi 3, 4, 5, Zero 2 W в 64-битном режиме | `pi-gen`, ветка `arm64`, Raspberry Pi OS Lite на trixie |
| `vibedpn-amd64.img` | N100 и другие x86-64 с UEFI | `debos`, Debian trixie, GRUB EFI |
| `vibedpn-arm64.img` | платы arm64 с UEFI | `debos`, Debian trixie, GRUB EFI |

32-битного образа нет: панель на нём не запускается, а Docker перестаёт выпускать пакеты для 32-битного Raspberry Pi OS.

**В образе:** Docker Engine, VibeDPN в `/opt/vibedpn`, команда `vibedpn`.
**Нет в образе:** паролей, SSH-ключей, роли коробки и образов контейнеров — их скачает первый `vibedpn up`.

---

## 2. Доступ к коробке

Образ публичный, поэтому доступ задаёте вы, до первой загрузки.

**Raspberry Pi:** в Raspberry Pi Imager выберите свой образ, откройте настройку ОС и задайте пользователя и SSH-ключ.
Imager запишет настройку cloud-init на загрузочный раздел.

**UEFI-образ:** после записи на диск на компьютере появится раздел `CIDATA`.
Скопируйте в нём `user-data.example` в `user-data` и впишите свой публичный SSH-ключ.
Без `user-data` войти в коробку нельзя.

---

## 3. Первый вход

При первом входе в консоль или по SSH сразу откроется `sudo vibedpn init`.
Он спросит роль и пароль панели; дальше — `sudo vibedpn up`.
Если выйти из мастера, он откроется снова при следующем входе, пока коробка не настроена.

---

## 4. Собрать самому

Нужен Linux с Docker и `/dev/kvm` — например, сама коробка N100; на macOS и в colima образы не собираются.

UEFI-образ — из корня репозитория, на N100 около 6 минут:

```bash
docker run --rm --device /dev/kvm -v "$PWD:/recipes" -w /recipes godebos/debos --fakemachine-backend=kvm --memory 4GB --scratchsize 8GB -t architecture:amd64 -t branch:main images/os/debos/vibedpn.yaml
```

Готовый файл — `vibedpn-amd64.img` в корне репозитория (`architecture:arm64` даёт `vibedpn-arm64.img`).

Образ Raspberry Pi — на arm64-машине с Docker или на amd64 с пакетом `qemu-user-binfmt`; нужны десятки гигабайт диска:

```bash
VIBEDPN_BRANCH=main sh images/os/pi-gen/build.sh
```

Готовый файл — `images/os/pi-gen/work/deploy/`.

Проверить собранное можно без железа: `tests/os/uefiBoot.sh` загружает UEFI-образ в QEMU и проходит первый вход, `tests/os/piImage.sh` разбирает образ Raspberry Pi — подробности в [devSetup.md](devSetup.md).

---

## 5. Что проверено

**Проверено сборкой и загрузкой (2026-09-20, коробка N100):** `vibedpn-amd64.img` собирается за 5 минут и в QEMU с OVMF проходит `tests/os/uefiBoot.sh`: cloud-init читает `user-data` с раздела `CIDATA`, заводит пользователя и растягивает корень на весь диск, ssh отвечает через 25 секунд, при первом входе открывается `vibedpn init`, `vibedpn init --role vps` и `vibedpn doctor` работают.
**Проверено сборкой и разбором:** образ Raspberry Pi собран нативно в CI (8 минут) и на N100 под эмуляцией (65 минут); `tests/os/piImage.sh` находит в нём Docker, VibeDPN, скрипт первого входа и seed cloud-init, а `vibedpn --version` и `docker --version` работают в chroot.
**Проверено сборкой и загрузкой в эмуляции:** `vibedpn-arm64.img` собран (32 минуты) и прошёл тот же тест под QEMU без аппаратного ускорения: ssh через 55 секунд, мастер, `init` и `doctor`.
**Не проверено:** загрузка на настоящем Raspberry Pi и на N100 с этого образа — коробка владельца живёт на обычной установке Debian.
**Проверено прогоном `os-images` в GitHub (35516308344):** все три образа собираются и проходят свои проверки; готовые файлы лежат артефактами прогона — 377, 346 и 705 МБ.
**Проверено по документации:** пользователь и стадии `pi-gen`, cloud-init в Raspberry Pi OS trixie, метка `CIDATA` у NoCloud — `docs/knowledge/platform/piGen.md`.
