# Хост: Debian и Raspberry Pi OS

## [провайдер] Ядра хостов и WireGuard

**Суть:** Debian 13 trixie (2025-08-09, ядро 6.12 LTS; arm64 и amd64 в списке архитектур) и
Debian 12 bookworm (2023-06-10, ядро 6.1) собирают `CONFIG_WIREGUARD=m`, `CONFIG_TUN=m`,
`CONFIG_NF_TABLES=m`; пакет `linux-image-arm64` предоставляет `wireguard-modules`. Ядра Raspberry Pi
(bcm2711 = Pi 4, bcm2712 = Pi 5, ветки rpi-6.12.y и rpi-6.18.y) — то же плюс `NF_TABLES_INET=y`,
`NFT_REJECT=m`, `NFT_FIB_INET=m`. Raspberry Pi OS с 2025-10-02 основана на trixie; апгрейд
с bookworm на месте не поддерживается — только чистый образ. Docker Engine на Pi OS 64-bit
ставится по инструкции для Debian (Stage 1).
**Применение:** `vibedpn doctor` проверяет наличие модуля `wireguard` и `nf_tables`, а не ставит их.

## [провайдер] Системный Python и установка Docker на хост

**Контекст:** `install.sh` (Stage 1) собирает CLI на системном Python без сторонних установщиков.
**Суть:** `python3-defaults` даёт 3.11.2 в bookworm и 3.13.5 в trixie — поэтому `requires-python`
ядра опущен до `>= 3.11`, а образ `core` остаётся на 3.12; тесты гоняются матрицей 3.11/3.12/3.13.
Docker ставится из официального apt-репозитория в формате deb822: файл
`/etc/apt/sources.list.d/docker.sources` с `Suites: $VERSION_CODENAME`, `Components: stable`,
`Architectures: $(dpkg --print-architecture)`, ключ `/etc/apt/keyrings/docker.asc`; пакеты
`docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin`. Страница
Raspberry Pi OS у Docker описывает только 32-битную (armhf, репозиторий `raspbian`), 64-битную
она прямо отсылает к инструкции для Debian — у 64-битной Pi OS и `ID=debian` в `/etc/os-release`.
**Источники:** https://sources.debian.org/api/src/python3-defaults/ ,
https://docs.docker.com/engine/install/debian/ , https://docs.docker.com/engine/install/raspberry-pi-os/ .
**Источники:** https://www.debian.org/News/2025/20250809 , https://www.debian.org/News/2023/20230610 ,
https://salsa.debian.org/api/v4/projects/kernel-team%2Flinux/repository/files/debian%2Fconfig%2Fconfig/raw?ref=debian%2F6.12%2Ftrixie ,
https://raw.githubusercontent.com/raspberrypi/linux/rpi-6.18.y/arch/arm64/configs/bcm2712_defconfig ,
https://www.raspberrypi.com/news/trixie-the-new-version-of-raspberry-pi-os/ ,
https://wiki.debian.org/WireGuard , https://packages.debian.org/trixie/wireguard .
