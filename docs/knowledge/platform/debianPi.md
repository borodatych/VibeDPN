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
**Источники:** https://www.debian.org/News/2025/20250809 , https://www.debian.org/News/2023/20230610 ,
https://salsa.debian.org/api/v4/projects/kernel-team%2Flinux/repository/files/debian%2Fconfig%2Fconfig/raw?ref=debian%2F6.12%2Ftrixie ,
https://raw.githubusercontent.com/raspberrypi/linux/rpi-6.18.y/arch/arm64/configs/bcm2712_defconfig ,
https://www.raspberrypi.com/news/trixie-the-new-version-of-raspberry-pi-os/ ,
https://wiki.debian.org/WireGuard , https://packages.debian.org/trixie/wireguard .
