# fail2ban на коробке: где он врёт про себя

Проверено 2026-09-18 на коробке владельца — Debian 13 trixie, fail2ban 1.1.0-8, nftables,
вход по ssh с паролем разрешён (решение владельца: домашняя коробка без публичного IP).
Дропин джейла — `host/fail2ban/vibedpn-sshd.local`, кладёт `install.sh`.

## Служба `active` не значит, что она банит

Три разных факта, и первые два ничего не говорят о третьем:

- служба `active` — сервер запущен
- джейл `sshd` есть в `fail2ban-client status` — журнал читается, нарушители считаются
- у джейла есть **действие** — есть чем банить

На коробке был ровно средний случай: `Currently banned: 0`, `Total failed` растёт,
а `fail2ban-client get sshd actions` отвечает `No actions for jail sshd`.
Бан в таком состоянии — запись в собственной базе fail2ban и больше ничего.

## Как в это состояние попадают

`reload` со **сменой `banaction`** оставляет джейл без действий вообще.
В `/var/log/fail2ban.log` это выглядит так (обе строки — на одном reload):

```
NOTICE  [sshd] Flush ticket(s) with nftables-multiport
NOTICE  [sshd] Flush ticket(s) with nftables
```

Старое действие смыто, новое не добавлено, ошибок нет, служба `active`, `reload` ответил `OK`.
Лечится только `restart`. Проверено дважды: первый раз случайно (установщик делал reload),
второй — воспроизведением (подмена `banaction` в дропине + reload).

`reload` **без** смены `banaction` действие не трогает — проверено отдельно.

Отсюда правило в `install.sh`: после укладки дропина спрашивать у сервера действия джейла и
перезапускать службу, если их нет. Смотреть на файл бесполезно — файл при поломке на месте.
Ответа сервера надо **дождаться**: сокет открывается позже, чем поднимается юнит, и вопрос,
заданный сразу после `restart`, выглядит как немой джейл (установщик из-за этого один раз
напечатал ложную тревогу).

## Таблица появляется по первому бану

`nft list tables` сразу после старта джейла таблицы `inet f2b-table` не показывает — это норма,
fail2ban стартует действие on demand. Таблица, цепочка и правило появляются при первом бане:

```
table inet f2b-table
  chain f2b-chain { type filter hook input priority filter - 1; policy accept;
    tcp dport 22 ip saddr @addr-set-sshd reject with icmp port-unreachable }
```

Поэтому `doctor` не имеет права ругаться на отсутствие таблицы при нуле банов; отказ — это
джейл без действий и баны, которых нет в таблице.

## `nftables-multiport` устарел

В 1.1.0 файл `action.d/nftables-multiport.conf` в собственной шапке пишет:
`Obsolete: superseded by nftables[type=multiport]`. Дебиановский `jail.d/defaults-debian.conf`
по умолчанию ставит `banaction = nftables`. В дропине используется `nftables[type=multiport]`;
в списке действий джейла оно показывается именем `nftables`.

## Сквозная проверка, которая что-то доказывает

Бан действует на весь адрес и не делает исключения для established, поэтому проверять со своего
адреса нельзя — потеряешь ssh на час. Проверка с адреса контейнера на самой коробке:

```bash
docker run --rm alpine sh -c "apk add --no-cache openssh-client sshpass >/dev/null;
  for i in 1 2 3 4 5 6; do sshpass -p wrongpass ssh -o PreferredAuthentications=password \
    -o PubkeyAuthentication=no -o StrictHostKeyChecking=no dpn@<адрес коробки> true; done"
```

Как это выглядело: пять `Permission denied`, шестая попытка — `Connection refused` (у
`nftables` `blocktype = reject`, отказ мгновенный), `Banned IP list: 172.17.0.2`,
`elements = { 172.17.0.2 }` в наборе. После `set sshd unbanip` тот же адрес снова получает
`Permission denied` — то есть доходит до sshd.

## Цена, которую надо знать

Бан по адресу бьёт и по входу с ключом. Пять промахов паролем с адреса администратора — час без
ssh с него. В дропине `ignoreip` только `127.0.0.1/8 ::1`: свой текущий адрес туда вписывать
нельзя, он меняется, а исключение останется навсегда.

Источники: файлы `action.d/*.conf` и `jail.d/defaults-debian.conf` пакета fail2ban 1.1.0-8 на
самой коробке; `man jail.conf(5)` про порядок чтения `jail.local` и `jail.d/*.local`.
