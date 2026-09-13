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

Образ Raspberry Pi — на arm64-машине с Docker, нужны десятки гигабайт диска:

```bash
VIBEDPN_BRANCH=main sh images/os/pi-gen/build.sh
```

Готовый файл — `images/os/pi-gen/work/deploy/`.

UEFI-образы — `debos` в контейнере:

```bash
docker run --rm --privileged -v "$PWD:/recipes" -w /recipes/images/os/debos godebos/debos --disable-fakemachine -t architecture:amd64 -t branch:main vibedpn.yaml
```

---

## 5. Что проверено

**Проверено сборкой:** пока ничего — статус каждого образа ведётся в `docs/roadmap.md`, Stage 12.
**Проверено по документации:** пользователь и стадии `pi-gen`, cloud-init в Raspberry Pi OS trixie, метка `CIDATA` у NoCloud — `docs/knowledge/platform/piGen.md`.
