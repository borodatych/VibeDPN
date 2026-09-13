# Архитектуры образов коробки: что поддерживают Docker и Bun

## [провайдер] 32-битный arm уходит у Docker, Bun его не знает

**Контекст:** Stage 12, готовые образы под архитектуры железа, 2026-09-13.

**Docker Engine на Raspberry Pi OS:**
32-битный (armhf) поддерживается для Bookworm 12 и Bullseye 11.
«Docker Engine v28 will be the last major version to support Raspberry Pi OS 32-bit (armhf)» — с v29 пакетов для armhf нет.
64-битным Pi документация велит ставить пакеты Debian `arm64`.
Устройства на ARMv6 (Raspberry Pi 1, Zero) официально не поддерживаются.

**Bun:** в документации установки — только Linux x64 и Linux ARM64 (плюс macOS и Windows); 32-битного ARM в списке нет.
Для x64 нужен SSE4.2 (Intel Nehalem, AMD Bulldozer и новее) — N100 подходит.

**Хост сборки (исполнением, colima VM, Ubuntu 24.04 aarch64):** systemd 255, пакет `mkosi` — кандидат 20.2-1, отдельного пакета `systemd-repart` нет, `qemu-user-static` не установлен; CPU без режима AArch32.

**Как применять:** полноценный образ (с панелью) возможен только для amd64 и arm64; armhf — без панели и на последней ветке Docker.

**Источники:** https://docs.docker.com/engine/install/raspberry-pi-os/ ; https://bun.com/docs/installation
