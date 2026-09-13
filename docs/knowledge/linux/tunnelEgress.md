# Выход пиров туннеля в интернет через VPS

## [провайдер] Accept в своей nft-таблице не отменяет DROP от Docker

**Контекст:** Stage 3, NAT пиров на VPS (2026-09-13). `wg-server` живёт в сети хоста, значит трафик
пира `wg0` → интернет идёт через хуки forward и postrouting самого хоста.
**Суть:** базовые цепочки разных таблиц на одном хуке проходятся все по порядку приоритета;
`accept` в одной цепочке не окончателен — пакет идёт в следующую, а `drop` в любой из них
окончателен. Docker, включая `ip_forward`, ставит `-P FORWARD DROP` в `ip filter` (через
`iptables-nft`), поэтому `accept` в `inet vibedpn_egress` пересылку не открывает. Для этого у
Docker есть цепочка `DOCKER-USER` (первый переход из FORWARD) — правило в ней и есть официальный
путь «пропустить трафик между интерфейсами хоста». `ip-forward-no-drop` в `daemon.json` тоже снял
бы DROP, но это правка чужой конфигурации хоста и снятие защиты для всех интерфейсов сразу.
С экспериментальным nftables-бэкендом Docker DROP не ставит и `DOCKER-USER` нет — тогда достаточно
нашей таблицы.
**Как устроено у нас:** `engine/router.py` грузит `inet vibedpn_egress` (forward с policy accept:
отбросить адрес туннеля не с `wg0` и новые соединения из интернета в `wg0`; postrouting
masquerade подсети туннеля не в `wg0`) и приводит наши правила `DOCKER-USER` (метка
`-m comment --comment vibedpn-egress`) к нужным: план строится сравнением с `iptables -S`,
старая подсеть и дубли удаляются, недостающие вставляются в начало (у старых Docker цепочка
кончается RETURN). Чужие правила владельца не трогаются.
**Факты исполнением (Docker 29.5.2, colima VM, образ debian:trixie-slim + iptables):**
`iptables-nft -S DOCKER-USER` печатает `-N DOCKER-USER` и правила ровно в форме
`-s 10.78.0.0/24 -i wg0 ! -o wg0 -m comment --comment vibedpn-egress -j ACCEPT` и
`-d … ! -i wg0 -o wg0 -m conntrack --ctstate RELATED,ESTABLISHED -m comment …` (порядок состояний
печатается так, как бы их ни задали); при наличии legacy-таблиц первой строкой идёт
`# Warning: iptables-legacy tables present…` — парсер берёт только строки `-A DOCKER-USER`.
Отсутствующая цепочка: код 1 и «iptables: No chain/target/match by that name.» — у обоих
бэкендов. Бэкенд выбирается по тому, где цепочка есть, `nft` первым; ошибки legacy-бэкенда на
nft-хосте считаются «не здесь», прочие ошибки nft-бэкенда — отказ старта.
**Грабли ревью:** `ACCEPT` в `DOCKER-USER` окончателен для iptables-цепочки FORWARD, поэтому
`-i wg0 ! -o wg0` открывает пиру не только интернет, но и `docker0`/`br-*` — цепочка `DOCKER`,
которая режет доступ к неопубликованным портам, до пакета уже не доходит. Закрывается drop в
своей nft-таблице (drop окончателен через все таблицы): от подсети туннеля в `docker0`, `br-*` и
в link-local/RFC 1918/CGNAT (иначе пир читает метаданные облака на 169.254.169.254). Порядок в
`DOCKER-USER` значим: наш `ACCEPT` под чужим `DROP` или `RETURN` мёртв — «правило есть в выводе»
не значит «работает», проверяется позиция.
**Грабли:** `iptables -w` ждёт блокировку `/run/xtables.lock` своего пространства имён — в
контейнере это не файл хоста, так что гонка с `dockerd` за правку таблицы теоретически возможна;
ядро правит `DOCKER-USER` только при старте. Переживают ли наши правила перезапуск `dockerd` —
проверено smoke (см. roadmap), при перезапуске демона контейнеры, включая `core`, стартуют заново
и правила применяются снова.
**Источники:** https://docs.docker.com/engine/network/packet-filtering-firewalls/ ,
https://docs.docker.com/engine/network/firewall-iptables/ (Allow forwarding between host interfaces),
https://wiki.nftables.org/wiki-nftables/index.php/Configuring_chains (Base chain priority).
