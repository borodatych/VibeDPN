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
**Источники (модуль и пакеты):** https://lists.zx2c4.com/pipermail/wireguard/2020-March/005206.html ,
https://git.zx2c4.com/wireguard-tools/plain/src/wg-quick/linux.bash ,
https://raw.githubusercontent.com/WireGuard/wireguard-go/master/tun/tun_linux.go ,
https://raw.githubusercontent.com/linuxserver/docker-wireguard/master/README.md ,
https://raw.githubusercontent.com/torvalds/linux/master/Documentation/networking/ip-sysctl.rst ,
https://pkgs.alpinelinux.org/package/v3.24/main/x86_64/wireguard-tools ,
https://pkgs.alpinelinux.org/package/v3.24/main/x86_64/wireguard-tools-wg-quick ,
https://pkgs.alpinelinux.org/package/v3.24/main/x86_64/nftables , https://alpinelinux.org/releases/ .

## [провайдер] Свой entrypoint вместо wg-quick: что нужно повторить руками

**Контекст:** Stage 3, чекбокс 1 — образ `vibedpn/wg`, режимы `server` и `client`.
**Суть:** `wg setconf` понимает только то, что описано в `wg(8)`: в `[Interface]` — `PrivateKey`,
`ListenPort`, `FwMark`, в `[Peer]` — `PublicKey`, `PresharedKey`, `AllowedIPs`, `Endpoint`,
`PersistentKeepalive`. Остальные ключи привычного `.conf` (`Address`, `MTU`, `DNS`, `Table`,
`PreUp/PostUp/PreDown/PostDown`, `SaveConfig`) придумал `wg-quick` — он их вырезает перед
`setconf` и исполняет сам; наш entrypoint делает то же (список ключей — из `parse_options`
в `wg-quick/linux.bash`). Ключи регистронезависимы, разделитель — `=` с любыми пробелами и
табами, комментарий — от `#` до конца строки: всё это встречается в реальных `.conf`, поэтому
разбор в тесте проверяется именно такой строкой. Дальше руками: `ip link add wg0 type
wireguard`, `wg setconf`, `ip address add` на каждый `Address`, `ip link set mtu … up`
(дефолт 1420), маршрут на каждый `AllowedIPs` (`wg show wg0 allowed-ips` — источник правды
после `setconf`).
**`AllowedIPs = 0.0.0.0/0` требует policy routing, а не default route:** обычный `default dev
wg0` отправил бы в туннель и сами зашифрованные пакеты. Приём wg-quick (`add_default`):
`wg set wg0 fwmark 51820`, `ip route replace default dev wg0 table 51820`, `ip rule add not
fwmark 51820 table 51820`, `ip rule add table main suppress_prefixlength 0` — последнее правило
оставляет конкретные маршруты main (свой бридж), игнорируя её default. Нужен
`net.ipv4.conf.all.src_valid_mark=1` (он уже в `compose.yaml`).
**Kill-switch** живёт в netns самого контейнера (хост меняет только `engine/router.py`):
`table inet vibedpn_wg` с `output` policy drop — пропускаем `lo`, `oifname wg0`,
`meta mark 51820` (свои шифрованные пакеты) и `fib daddr type local`; `forward` policy drop —
только `oifname wg0` и обратное established; `postrouting` — `masquerade` в `wg0`. Это nft-форма
того же правила, что `wg-quick(8)` приводит как «kill-switch» (`iptables -I OUTPUT ! -o %i -m
mark ! --mark $(wg show %i fwmark) -m addrtype ! --dst-type LOCAL -j REJECT`). Проверено
исполнением: при живом туннеле пинг на шлюз бриджа и наружу не проходит, трафик в туннель — да.
**Интерфейс «упал» — это два разных состояния:** удалён и административно down. Оба ловит
`ip -o link show up dev wg0` (пусто в обоих случаях). После `ip link set wg0 down` ядро
выбрасывает маршруты через устройство, и поднятие обратно туннель не чинит — поэтому entrypoint
выходит ненулевым кодом, а `restart: unless-stopped` собирает всё заново; kill-switch при этом
не даёт трафику утечь в промежутке (проверено: контейнер перезапустился, пинг наружу так и не
прошёл). В POSIX `sh` сигнал во время `sleep` доходит до обработчика только если спать в фоне
и ждать через `wait`.
**Метку ставим конфигом, а не после `setconf`:** kill-switch выпускает наружу только помеченные
пакеты, поэтому `FwMark = 51820` дописывается в `[Interface]` того, что уходит в `wg setconf`
(`wg(8)` этот ключ понимает; `wg show wg0 fwmark` → `0xca6c`). Иначе при `AllowedIPs` без
`0.0.0.0/0` метки не было бы вовсе (`wg show wg0 fwmark` → `off`), и сплит-туннель либо не
поднимался вовсе, либо жил на случайности. Проверено на прежнем варианте: конфиг без
`PersistentKeepalive` не давал ни одного handshake — интерфейс up, контейнер считает себя
здоровым, связи нет; конфиг с keepalive работал только потому, что первый handshake успевал уйти
до установки правил, а дальше пакеты проходили по `ct state established` (запись conntrack
обновляется на приоритете -200, до фильтра, поэтому даже дропнутые keepalive её продлевают —
туннель ломался не «по истечении», а при потере записи: флаш, переполнение, смена endpoint). Поэтому же таблица nft ставится **до** создания интерфейса: `oifname "wg0"`
принимается и для несуществующего устройства, окна без правил не остаётся.
**Keepalive обязателен для клиента-шлюза:** он за NAT, и без `PersistentKeepalive` простаивающий
туннель перестаёт пересогласовываться, а пир забывает трансляцию. Пирам без ключа entrypoint
проставляет 25 с сам (`wg set … persistent-keepalive`) и пишет об этом в лог.
**Сторож смотрит не только на интерфейс:** `wg` резолвит `Endpoint` один раз, поэтому сменивший
адрес VPS чинится только пересозданием туннеля. У клиента сторож после минуты отсрочки проверяет
возраст handshake тем же порогом и выходит ненулевым кодом — рестарт заодно резолвит имя заново.
**Остаток в netns хоста:** `wg-server` работает с `network_mode: host`, wg0 живёт в netns самой
VPS и переживает контейнер, убитый SIGKILL или упавший после создания интерфейса. Тогда
`ip link add` отвечает «File exists», и контейнер уходит в вечный рестарт с сообщением про
модуль ядра (проверено исполнением). Поэтому перед созданием интерфейс сносится, если остался.
**Грабля awk:** `print a > b` — это перенаправление вывода в файл `b`, а не сравнение; тернарник
в `print` нужно брать в скобки, иначе функция молча отдаёт пустую строку (так сломался расчёт
возраста handshake, healthcheck стал падать при живом туннеле).
**Healthcheck:** client — handshake не старше 180 с (`wg show wg0 latest-handshakes`; пир с
`PersistentKeepalive` пересогласуется примерно раз в две минуты), server — достаточно поднятого
wg0, пиров может не быть.
**Источники:** https://man7.org/linux/man-pages/man8/wg.8.html (setconf, ключи конфига),
https://git.zx2c4.com/wireguard-tools/plain/src/man/wg-quick.8 (kill-switch, ключи wg-quick),
https://git.zx2c4.com/wireguard-tools/plain/src/wg-quick/linux.bash (`parse_options`,
`add_default`); исполнение 2026-09-12 (три контейнера и host-netns сервер на colima,
`tests/wg/tunnel.sh`; ревью 2 линзы + скептики).
