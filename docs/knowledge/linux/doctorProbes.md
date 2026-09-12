# Проверки хоста для `doctor`

## [провайдер] `ss`, модули ядра и `ip_forward`: что и как читать

**Контекст:** `vibedpn doctor` v1 (Stage 1). Факты сняты исполнением 2026-09-12.
**Суть:** `ss -H -lntup` отдаёт строки `proto state recvq sendq local peer [users:(("имя",pid=…,fd=…))]`;
локальный адрес бывает `0.0.0.0:53`, `127.0.0.53%lo:53` (суффикс интерфейса), `*:3000` и `[::]:80`
для IPv6-any — парсер снимает `%iface` и скобки, `*`/`::`/`0.0.0.0` считает «любой адрес». Имена
процессов есть только под root. Заглушка systemd-resolved слушает `127.0.0.53:53` — она не мешает
AdGuard, который привязан к адресу коробки в LAN; конфликт — слушатель на любом адресе (dnsmasq
от NetworkManager) или на том же LAN-адресе. Модуль ядра: доступный, но не загруженный модуль в
`/sys/module` не виден (на ВМ colima `wireguard` — sysfs нет, `modprobe -n -q` → 0), поэтому проверка
— sysfs **или** `modprobe -n -q`; `nf_tables` у хоста с Docker всегда загружен. `ip_forward`:
Docker при старте сам включает `net.ipv4.ip_forward` и `net.ipv6.conf.all.forwarding`, **но
одновременно ставит политику DROP на пересылку** — «will prevent your Docker host from acting as
a router»; снимается опцией `ip-forward-no-drop` в `daemon.json`, а с nftables-бэкендом Docker
forwarding не трогает вовсе. Для Stage 4 это значит: транзит LAN → шлюзы идёт через FORWARD и
должен быть явно разрешён (DOCKER-USER или `ip-forward-no-drop`) — вдобавок к `nat-unprotected`
([docker/directRouting.md](../docker/directRouting.md)).
**Грабли без sudo (ревью 2026-09-12):** на Debian PATH обычного пользователя не содержит sbin,
и `modprobe` «не найден» — искать его по `/usr/sbin:/sbin` явно, а отсутствие считать «не смогли
проверить», не «модуля нет»; `Path.is_file()` внутри каталога с правами 000 бросает
`PermissionError` на Python < 3.14 (root-only `secrets/`); `ss` отсутствует или падает — порты
«не проверены», а не «свободны»; при недоступном Docker занятый порт нельзя приписать чужому
процессу — это может быть свой контейнер. Правило: неснятый факт — `warn` с подсказкой, никогда
не молчаливый `ok`.
**Источники:** https://man7.org/linux/man-pages/man8/ss.8.html , фикстуры `core/tests/fixtures/ss_*.txt`,
https://man7.org/linux/man-pages/man8/modprobe.8.html (`-n`),
https://docs.docker.com/engine/network/packet-filtering-firewalls/ (IP forwarding, `ip-forward-no-drop`).
