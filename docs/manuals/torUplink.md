# Бесплатный выход через Tor

Как открыть через коробку заблокированные сайты и Telegram, не заводя ни аккаунтов, ни криптовалюты, ни своей VPS.
Коробка подключается к сети Tor через мосты Snowflake: они проходят там, где сам Tor заблокирован.

## Что это даёт и чего не даёт

Работает: сайты и Telegram — всё, что ходит по TCP.
Не работает: звонки, игры, прочий UDP. Браузеры сами переходят с QUIC на обычный HTTPS.
Скорость через Snowflake — около 1 Мбит/с: страницы и сообщения да, видео нет.
Часть сайтов показывает выходным узлам Tor капчу.

Если выход упал или ещё не подключился, трафик через него стоит, а не уходит напрямую.

## Проще всего — через панель

1. Страница **«Выходы»** → карточка **«Бесплатный выход через Tor»** → **«Включить»**.
2. Подождать строку «Применено» и ещё минуту-две: коробка подключается к Tor.
3. Страница **«Правила»**: добавить сайт с каналом **«Через Tor»**.

Ниже — то же из терминала, плюс Telegram.

## 1. Включить выход

```bash
sudo vibedpn tor enable
sudo vibedpn up
```

Проверить, что подключился — контейнер `tor` в состоянии `healthy`:

```bash
sudo vibedpn status
```

## 2. Отправить через него сайты

Умный режим: через Tor идут только перечисленные сайты, остальное напрямую.

```bash
sudo vibedpn rule add rutracker.org tor
sudo vibedpn rule add lostfilm.today tor
sudo vibedpn mode smart
```

Правило действует и на поддомены: `rutracker.org` покрывает `www.rutracker.org`.

## 3. Telegram

Приложение Telegram соединяется с адресами своих дата-центров, а не по именам, поэтому ему нужны правила по сетям.
Официальный список сетей: https://core.telegram.org/resources/cidr.txt — берутся строки IPv4.

```bash
for net in 91.108.56.0/22 91.108.4.0/22 91.108.8.0/22 91.108.16.0/22 91.108.12.0/22 \
  149.154.160.0/20 91.105.192.0/23 91.108.20.0/22 185.76.151.0/24; do
  sudo vibedpn net add "$net" tor
done
sudo vibedpn rule add telegram.org tor
sudo vibedpn rule add t.me tor
sudo vibedpn rule add telegra.ph tor
```

Список сетей на 17.09.2026; перед вводом сверить с официальным файлом.

## Весь трафик через Tor

```bash
sudo vibedpn upstream tor
sudo vibedpn mode full
```

Российские сервисы часто не пускают зарубежные адреса. Их оставить напрямую правилом `direct`:

```bash
sudo vibedpn rule add gosuslugi.ru direct
```

Одно устройство целиком через Tor, остальные как были:

```bash
sudo vibedpn device set <MAC> tor
```

## Проверить

```bash
sudo vibedpn doctor --network
```

В строке `exit tor` — адрес узла Tor, не ваш.
С устройства LAN откройте сайт, показывающий ваш IP, для сайта из правил: адрес должен смениться.

## Если не подключается

Смотреть журнал шлюза:

```bash
sudo vibedpn logs tor
```

**`Bootstrapped` стоит на месте.** Мосты не проходят.
Встроенные мосты меняются с выпусками Tor Browser: свежие — в `pt_config.json` проекта Tor Browser, раздел `bridges.snowflake`
(https://gitlab.torproject.org/tpo/applications/tor-browser-build/-/raw/main/projects/tor-expert-bundle/pt_config.json).
Свои строки мостов кладутся в `config.yaml`, после правки — `sudo vibedpn up`:

```yaml
upstreams:
  tor:
    enabled: true
    bridges:
      - "snowflake 192.0.2.3:80 ..."
```

Поддерживаются транспорты `snowflake`, `obfs4` и `meek_lite`. Встроенные obfs4-мосты Tor Browser у Ростелекома в сентябре 2026 не проходили.

**Сайт открывается медленно или с капчей.** Это особенность выходных узлов Tor, а не коробки.

## Выключить

```bash
sudo vibedpn tor disable
sudo vibedpn up
```

Сначала снимите правила, сети и политики устройств с каналом `tor` — иначе коробка откажется выключать выход, через который идёт трафик.
