# Лицензии

## [договорённость] MIT у нас, GPL у контейнеров — конфликта нет

**Контекст:** kickoff: «myst — GPL-3, мы его не форкаем, а запускаем как отдельный контейнер».
**Суть:** проверено 2026-09-11: `mysteriumnetwork/node` — GPL-3.0 (LICENSE и README),
AdGuard Home — GPL-3.0 (LICENSE.txt), wireguard-tools — GPL-2.0 (COPYING). VibeDPN не линкуется
с ними и не включает их код: контейнеры общаются через сокеты, HTTP (TequilAPI) и аргументы командной
строки, а это по GPL FAQ «MereAggregation» — механизмы связи между отдельными программами;
GPLv3 §5 прямо говорит, что включение GPL-работы в агрегат не распространяет GPL на остальные
части. Наш код (обвязка, роутер, CLI, UI) остаётся под MIT; ничего из GPL-репозиториев в наш
не копируется (образ `vibedpn/wg` ставит `wireguard-tools` пакетом Alpine, не вшивает исходники).
**Применение:** любое копирование кода из репозиториев myst/AdGuard/WireGuard в наш —
лицензионная проблема, а не только стилистическая.
**Источники:** https://raw.githubusercontent.com/mysteriumnetwork/node/master/LICENSE ,
https://raw.githubusercontent.com/AdguardTeam/AdGuardHome/master/LICENSE.txt ,
https://git.zx2c4.com/wireguard-tools/tree/COPYING ,
https://www.gnu.org/licenses/gpl-faq.html#MereAggregation ,
https://choosealicense.com/licenses/gpl-3.0/ (текст GPLv3, §5, зеркало — gnu.org режет запросы),
https://choosealicense.com/licenses/mit/ .
