# Bot API Telegram и выход бота: как коробка ходит в Telegram

**Контекст:** Telegram-бот ядра (решение 31, `engine/telegram.py`, `api/telegram.py`), 2026-09-23.
Бот должен ходить в Telegram так же, как устройство дома: через выход по правилам коробки и под её kill switch.

## [факт] Запрос и ответ Bot API

Каждый вызов — `https://api.telegram.org/bot<token>/<METHOD>`, только HTTPS, GET или POST; параметры можно слать JSON-телом.
Ответ — JSON с полем `ok`; при `ok: true` результат лежит в `result`, иначе есть `description`, `error_code` и иногда `parameters`.
`parameters.retry_after` — сколько секунд ждать перед повтором.
`sendMessage`: `chat_id` и `text` длиной 1–4096 символов после разбора разметки.
`getMe` — «простой метод проверить токен».
**Как применять:** токен — часть каждого URL, поэтому ошибка соединения называет только класс сбоя, никогда не URL; ошибка Telegram — его собственное `description`.

## [опыт] Неверный токен: 401, неразборчивый — 404

Запрос `getMe` с выдуманным токеном вида `123456:AAAA-fake_token` 23.09.2026 получил `{"ok":false,"error_code":401,"description":"Unauthorized"}`, токен без двоеточия — `404 Not Found`.
**Как применять:** оба кода значат «Telegram не знает этот токен» (`TelegramError.rejected`); API ядра отвечает на них 422, а не 503.

## [факт] getUpdates и привязка чата по ссылке

`offset` — первый возвращаемый update; update подтверждён, как только `getUpdates` вызван с `offset` больше его `update_id`.
`timeout` — длинный опрос в секундах, по умолчанию 0 — обычный короткий опрос.
Пока у бота стоит webhook, `getUpdates` не работает.
Ссылка `https://t.me/<бот>?start=<параметр>` открывает чат с ботом, и по «Старт» бот получает `/start <параметр>`; в параметре только `A-Z`, `a-z`, `0-9`, `_` и `-`, до 64 символов.
**Как применять:** код привязки — `secrets.token_urlsafe(16)`, 22 символа из этого алфавита; ядро слушает `getUpdates` только 15 минут, пока ссылка ждёт, и привязывает личный чат (`chat.type == "private"`), приславший `/start` с этим кодом.

## [факт] Не чаще сообщения в секунду в один чат

FAQ Telegram: в один чат — не чаще одного сообщения в секунду, иначе рано или поздно 429; в группу — не больше 20 в минуту.
**Как применять:** события за 10 секунд склеиваются в одно сообщение, а пауза из `retry_after` соблюдается.

## [грабли] httpx ставит опции сокета после connect — метка выхода не успевает

`httpx.HTTPTransport(socket_options=[...])` передаёт опции в httpcore, а httpcore 1.0.9 в `_backends/sync.py` сначала делает `socket.create_connection`, потом `setsockopt` для каждой опции.
`SO_MARK`, поставленный так, опаздывает: маршрут SYN уже выбран по основной таблице, рукопожатие уходит мимо выхода, а kill switch бота не держит.
Этот план был в согласованном плане бота («`HTTPTransport(socket_options=...)` есть — для `SO_MARK`») и поймался чтением исходника до первой строки кода.
**Как применять:** соединение бота — `http.client` с переопределённым `connect`: сокет `AF_INET`, `SO_MARK` до `connect`, затем `connect` к адресу. Тест `test_the_mark_is_on_the_socket_before_it_connects` проверяет порядок вызовов.

## [факт] SO_MARK: нужна CAP_NET_ADMIN, имя — только в Linux

man socket(7): `SO_MARK` метит каждый пакет сокета для маршрутизации по меткам; ставить его может процесс с `CAP_NET_ADMIN` или, с Linux 5.17, `CAP_NET_RAW`.
У контейнера `core` есть `NET_ADMIN`, и он в сети хоста, поэтому метка попадает в `ip rule` хоста.
Python называет `socket.SO_MARK` только на Linux: в образе ядра это 36, на macOS константы нет.
**Как применять:** на системе без `SO_MARK` сокет с меткой выхода не создаётся вовсе — лучше ошибка, чем тихий выход напрямую.

## [опыт] Подключение к найденному адресу с проверкой сертификата по имени

Бот сам узнаёт адрес `api.telegram.org` (через DoH ядра) и подключается к нему, а TLS ведёт с именем: `HTTPSConnection` с именем хоста и своим `connect` отдаёт это имя и в SNI, и в проверку сертификата.
Проверено 23.09.2026 с Mac: подключение к `149.154.166.110` с именем `api.telegram.org` — ответ Bot API 401 на выдуманный токен; тот же адрес с именем `example.com` — `SSLCertVerificationError`.
У httpcore есть расширение запроса `sni_hostname` для той же цели, но опоздание опций сокета оно не лечит.
**Как применять:** правило выхода считается по тому адресу, к которому бот действительно подключится — второй резолв мог бы дать другой.

**Источники:** https://core.telegram.org/bots/api (запросы, ответы, `ResponseParameters`, `getUpdates`, `getMe`, `sendMessage`, формат токена); https://core.telegram.org/bots/features#deep-linking (ссылка `?start=`, алфавит и 64 символа); https://core.telegram.org/bots/faq (ограничения частоты, 429); https://man7.org/linux/man-pages/man7/socket.7.html (`SO_MARK`, `CAP_NET_ADMIN`, `CAP_NET_RAW` с 5.17); https://www.encode.io/httpcore/extensions/ (`sni_hostname`); исходник httpcore 1.0.9 `httpcore/_backends/sync.py`, `SyncBackend.connect_tcp`.
