# WireGuard в контейнере (образ `vibedpn/wg`)

## [архитектура] Модуль ядра — хостовый, /dev/net/tun не нужен

**Контекст:** образ `vibedpn/wg` на Alpine для аплинка `vps` и сервера на VPS.
**Суть:** WireGuard в mainline с Linux 5.6; интерфейс создаётся через netlink
(`ip link add wg0 type wireguard`) и не трогает `/dev/net/tun` — он нужен только userspace
`wireguard-go` (`tun_linux.go` открывает `/dev/net/tun`). Контейнеру хватает `NET_ADMIN`;
`SYS_MODULE` + `/lib/modules` — только если модуль грузить изнутри (мы не грузим: Debian 12/13 и ядра
Raspberry Pi собирают `CONFIG_WIREGUARD=m`, см. [platform/debianPi.md](../platform/debianPi.md)).
Sysctl `net.ipv4.conf.all.src_valid_mark=1` нужен, когда маршрутизация идёт по fwmark (так делает
wg-quick для `AllowedIPs 0.0.0.0/0`): ядро учитывает метку в reverse-path проверке.
`net.ipv4.ip_forward=1` — для режима шлюза; смена сбрасывает per-interface настройки.
**Пакеты Alpine 3.24:** `wireguard-tools` — метапакет из `wireguard-tools-wg` (только `/usr/bin/wg`,
зависит лишь от musl) и `wireguard-tools-wg-quick` (тянет `bash`, `iproute2`, `openresolv`);
`nftables` 1.1.6; `wireguard-go` — в community. Берём `wireguard-tools-wg iproute2 nftables`:
маршруты и файрвол entrypoint задаёт явно, wg-quick с его собственной таблицей
`wg-quick-<iface>` в nft не нужен. Alpine 3.24.1 (2026-06-09), поддержка до 2028-06-01.
**Источники:** https://lists.zx2c4.com/pipermail/wireguard/2020-March/005206.html ,
https://git.zx2c4.com/wireguard-tools/plain/src/wg-quick/linux.bash ,
https://raw.githubusercontent.com/WireGuard/wireguard-go/master/tun/tun_linux.go ,
https://raw.githubusercontent.com/linuxserver/docker-wireguard/master/README.md ,
https://raw.githubusercontent.com/torvalds/linux/master/Documentation/networking/ip-sysctl.rst ,
https://pkgs.alpinelinux.org/package/v3.24/main/x86_64/wireguard-tools ,
https://pkgs.alpinelinux.org/package/v3.24/main/x86_64/wireguard-tools-wg-quick ,
https://pkgs.alpinelinux.org/package/v3.24/main/x86_64/nftables , https://alpinelinux.org/releases/ .
