# Transmission: RPC, образ, настройки и API ядра

## [torrents] Образ и как он настраивается

**Контекст:** необязательный торрент-клиент коробки (роли `home`, `client`), служба `transmission` в `compose.yaml`.
**Суть:**
- Образ `lscr.io/linuxserver/transmission:4.1.3-r0-ls364` (тег вида `<версия>-r0-ls<сборка>`, пин в `compose.yaml` через `TRANSMISSION_TAG`).
  Свой образ у Transmission не публикуется, linuxserver держит мультиарх (amd64, arm64) и принимает `PUID`/`PGID`.
  Тег и работу под `PUID=7756` проверили запуском на 15.10.2026: демон слушает, RPC отвечает.
- Переменные образа: `PUID`, `PGID`, `USER`, `PASS`, `FILE__PASS` (значение из файла), `WHITELIST` (в `rpc-whitelist`, включает проверку),
  `HOST_WHITELIST`, `PEERPORT` (в `peer-port`, выключает случайный порт), `UMASK`, `TRANSMISSION_WEB_HOME`.
  Тома: `/config` (там `settings.json`), `/downloads`, `/watch`.
- Скрипт старта (`init-transmission-config`) копирует `/defaults/settings.json`, только если `/config/settings.json` нет,
  и каждый старт переписывает через `jq` ключи `rpc-authentication-required`, `rpc-username`, `rpc-password`, `rpc-whitelist*`,
  `rpc-host-whitelist*`, `peer-port`, `umask`. Остальные ключи (в том числе `rpc-bind-address`) он не трогает.
  В умолчаниях образа `rpc-bind-address` — `[::]`, `download-dir` — `/downloads/complete`, `incomplete-dir` — `/downloads/incomplete`
  с `incomplete-dir-enabled: true`. Каталоги `complete` и `incomplete` под `/downloads` образ сам не создаёт
  (без них пишет `stat: cannot statx '/downloads/complete'`), поэтому их создаёт хост до старта.
- Привязку RPC к loopback образ переменной не даёт, поэтому ядро до старта записывает в `settings.json` ключ `rpc-bind-address`
  (`engine/transmission.py`). Transmission при выходе переписывает файл, но заданные ключи сохраняет.
- Пароль RPC в `settings.json` Transmission при старте превращает в соль-хэш. Пароль приходит из `secrets/transmission-rpc-pass`
  через `FILE__PASS`, а не лежит в `compose.yaml`.

**Ключи `settings.json`, которые пишет хост** (`vibedpn up`, `engine/transmission.py`; имена из Editing-Configuration-Files):
`rpc-bind-address` `127.0.0.1`, `rpc-port` `9091`, `download-dir` `/downloads/complete`, `incomplete-dir` `/downloads/incomplete`,
`incomplete-dir-enabled` `true`, `peer-port`, `peer-port-random-on-start` `false`, `port-forwarding-enabled` `false` (UPnP и NAT-PMP не предполагаются),
`speed-limit-down-enabled` и `speed-limit-up-enabled`, а числа `speed-limit-down` и `speed-limit-up` — только когда лимит включён.
Пароль, имя пользователя и `rpc-whitelist` (`127.0.0.1`) пишет сам образ из `FILE__PASS`, `USER`, `WHITELIST`.

**Правка файла и работающий демон** (проверено стендом `tests/e2e/torrents.sh`, 15.10.2026):
- Работающий демон переписывает файл при выходе и держит новое значение впереди файла: после `session_set` с лимитом 500 кБ/с файл ещё показывал `speed-limit-down: 100` и `false`.
  Поэтому хост, увидев отличие в ключе вроде `peer-port`, сначала останавливает клиент, потом пишет файл, а `up` его запускает. Разницу только в лимитах хост снимает вызовом `session_set` в работающем клиенте, без остановки;
  файл берёт лимиты только когда клиента нет. Без этого второй `vibedpn up` после лимита из панели перезапускал клиент.
- Демон в контейнере слушает RPC на `127.0.0.1:9091` и больше нигде (`ss -ltn`), без пароля отвечает `401`, работает под uid 7756 (`ps -C transmission-daemon -o uid=`).
  Peer-порт (по умолчанию 51413) демон открывает на всех адресах хоста (`0.0.0.0` и `[::]`); проброс порта на домашнем роутере владелец делает сам.
- Образ создаёт `/downloads/complete` и `/downloads/incomplete` только если они есть: без них пишет `stat: cannot statx`, поэтому хост создаёт обе папки до старта.

**Источники:**
- https://docs.linuxserver.io/images/docker-transmission/ (переменные, тома, `FILE__`)
- https://github.com/linuxserver/docker-transmission (скрипты `root/etc/s6-overlay/s6-rc.d/init-transmission-config/run`, `svc-transmission/run`, `root/defaults/settings.json`)
- https://github.com/transmission/transmission/blob/main/docs/Editing-Configuration-Files.md (ключи и семантика)

## [torrents] RPC Transmission 4.1

**Суть:**
- Адрес `POST http://127.0.0.1:9091/transmission/rpc`, HTTP Basic. Без заголовка `X-Transmission-Session-Id` (или с устаревшим) ответ `409`
  с правильным значением в заголовке ответа: клиент повторяет тот же запрос с ним. Без учётных данных — `401`.
- Протокол JSON-RPC 2.0 с именами `snake_case` (`torrent_get`, `percent_done`) — текущий; старый (`torrent-get`, `percentDone`) в 4.1.3
  ещё отвечает, но в спецификации помечен устаревшим. Ядро говорит только на новом. Проверено живым демоном 4.1.3
  (`rpc_version_semver` 6.0.1) 15.10.2026.
- `torrent_get`: `ids` — число, хэш-строка, список из них или `recently_active`; не найденный id даёт пустой список, не ошибку.
  Номера `id` не стабильны между перезапусками демона, хэш (`hash_string`) стабилен: API ядра отдаёт наружу хэш.
- `status`: 0 остановлен, 1 в очереди на проверку, 2 проверка, 3 в очереди на загрузку, 4 загрузка, 5 в очереди на раздачу, 6 раздача.
- `eta`: секунды; `-1` (неизвестно) и `-2` (недоступно) ядро отдаёт как `null`. `upload_ratio` `-1` и `-2` — тоже `null`.
- Приоритет файла в `file_stats[].priority`: `-1` низкий, `0` обычный, `1` высокий (проверено: `priority_low`/`priority_high` в `torrent_set`).
  Пустой массив в `files_wanted`/`priority_*` значит «все файлы», поэтому ядро пустой список индексов отвергает.
- `torrent_add`: `filename` (magnet или URL) либо `metainfo` (base64 тела `.torrent`), `download_dir`, `paused`. Ответ — `torrent_added`
  или `torrent_duplicate` с `hash_string`, `id`, `name`.
- `torrent_remove` с `delete_local_data`. `torrent_start`, `torrent_stop` берут `ids`.
- `session_get`/`session_set`: `speed_limit_down`, `speed_limit_down_enabled`, `speed_limit_up`, `speed_limit_up_enabled` (кБ/с).
- `free_space` (`path`) отвечает `size_bytes` и `total_size`; на несуществующий путь — ошибка кода 5 («No such file or directory»).
- Ошибка JSON-RPC: объект `error` с `code`, `message`, `data.error_string`.

**Источники:** https://github.com/transmission/transmission/blob/main/docs/rpc-spec.md ; живой демон из образа выше.

## [torrents] API ядра

Маршруты `/torrents/*` ядра (`core/vibedpn/api/torrents.py`); панель ходит к ним через свой прокси `/api/core/torrents/*`.
Правила для всех:
- Тела и ответы — JSON, числа в байтах и байтах в секунду, время в секундах Unix.
- `{id}` — хэш торрента (40 шестнадцатеричных символов, регистр не важен), не номер Transmission.
- Ошибки — `{"detail": "<фраза для оператора>"}`: `503` службы нет (`torrents.enabled: false`, контейнер не запущен, RPC молчит или отверг пароль);
  `404` нет такого торрента; `422` неверное тело; `502` Transmission ответил ошибкой.
- Ядро слушает только loopback и сам не проверяет вход: это дело панели.

### Торрент в списке (`TorrentSummary`)

```json
{
  "id": "7ad0393e3790590660678ef4e876a5248dcdad8d",
  "name": "ubuntu.iso",
  "status": "downloading",
  "progress": 0.42,
  "rate_down": 1048576,
  "rate_up": 2048,
  "eta": 3600,
  "size": 4800000000,
  "ratio": 0.1,
  "error": null
}
```

- `status`: `stopped`, `check_wait`, `checking`, `download_wait`, `downloading`, `seed_wait`, `seeding`.
- `progress` от 0 до 1. `eta` — секунды или `null`. `ratio` — число или `null`. `error` — фраза Transmission или `null`.

### `GET /torrents`

`200 {"torrents": [TorrentSummary, …], "rate_down": 0, "rate_up": 0}` — суммарные скорости по всем торрентам.

### `POST /torrents`

Тело `{"magnet": "magnet:?xt=…" | null, "torrent": "<base64 .torrent>" | null, "subdir": "films" | null, "paused": false}`:
ровно одно из `magnet` и `torrent`. `subdir` — подпапка внутри каталога загрузок (одно имя без `/` и `..`), по умолчанию корень.
`201 {"id": "<hash>", "name": "…", "duplicate": false}`; такой торрент уже есть — `200` с `duplicate: true`.

### `POST /torrents/{id}/start`, `POST /torrents/{id}/stop`

`204`. `404`, если торрента нет.

### `DELETE /torrents/{id}?data=false`

`204`. `data=true` удаляет и скачанные файлы.

### `GET /torrents/{id}`

`200` — `TorrentSummary` и поля:

```json
{
  "download_dir": "/srv/vibedpn/downloads/complete",
  "files": [{"index": 0, "name": "dir/a.mkv", "size": 1000, "done": 500, "wanted": true, "priority": "normal"}],
  "peers": [{"address": "203.0.113.5", "client": "qBittorrent 5.0", "progress": 0.5, "rate_down": 100, "rate_up": 0, "flags": "TDE"}],
  "trackers": [{"announce": "http://t.example/announce", "host": "t.example", "seeders": 12, "leechers": 3,
                "last_announce_ok": true, "last_announce_result": "Success", "last_announce_time": 1790000000}]
}
```

- `download_dir` — папка торрента на хосте: `torrents.download_dir`, `complete` и подпапка из `subdir`.
- `priority`: `low`, `normal`, `high`. У magnet-ссылки до получения метаданных `files` пуст.
- `seeders`, `leechers`: `null`, пока трекер не отвечал (Transmission отдаёт `-1`).

### `PUT /torrents/{id}/files`

Тело `{"indices": [0, 2], "wanted": true | null, "priority": "low" | "normal" | "high" | null}`.
`indices` не пуст (пустой список в Transmission значит «все файлы»), хотя бы одно из `wanted` и `priority` задано. `204`.

### `GET /torrents/session`, `PUT /torrents/session`

```json
{"speed_limit_down": 500, "speed_limit_down_enabled": true, "speed_limit_up": 100, "speed_limit_up_enabled": false}
```

Скорости в кБ/с. `GET` отдаёт ещё `rate_down`, `rate_up` (текущие, Б/с; при `PUT` игнорируются). `PUT` принимает любое подмножество
четырёх ключей, неизвестные отвергает (`422`); ответ — как у `GET`. Лимиты живут в самом Transmission и пережидают его перезапуск.

### `GET /torrents/storage`

```json
{
  "download_dir": "/srv/vibedpn/downloads",
  "free_bytes": 100000000000,
  "total_bytes": 500000000000,
  "egress": "direct",
  "storage": {"configured": true, "uuid": "1234-ABCD", "mounted": true},
  "devices": [{"uuid": "1234-ABCD", "label": "TORRENTS", "fstype": "exfat", "size": 1000000000000,
               "device": "/dev/sda1", "mountpoint": "/srv/vibedpn/usb", "supported": true, "current": true}],
  "scanned_at": 1790000000.0,
  "state": {"pending": false, "ok": true, "message": "", "finished_at": 1790000000.0}
}
```

- `download_dir` — каталог загрузок в представлении хоста (`torrents.download_dir`), а не контейнера.
- `free_bytes`, `total_bytes` — `null`, пока Transmission не ответил.
- `storage.configured` — задан ли USB-накопитель (`torrents.storage.uuid`), `mounted` — подключён ли он сейчас.
- `devices` — блочные устройства с файловой системой, которые хост видел при последнем просмотре; `supported` — файловая система из
  `ext4`, `exfat`, `ntfs`; `current` — накопитель, выбранный сейчас. `scanned_at` — когда хост смотрел (`null`: ещё нет).
- `GET /torrents/storage?refresh=true` просит хост посмотреть устройства заново (задача хоста, секунды); ответ приходит сразу со старым
  списком и `state.pending: true`, панель повторяет запрос, пока `pending` не станет `false`.

### `PUT /torrents/storage`

Тело `{"uuid": "1234-ABCD" | null}`: выбрать накопитель по UUID файловой системы или `null` вернуться на каталог по умолчанию.
Ядро проверяет UUID по списку устройств хоста (`422` для неизвестного или неподдерживаемого), записывает `torrents.storage.uuid`
в `config.yaml` и просит хост применить (`vibedpn up` монтирует диск и пересоздаёт `transmission`). `202` с телом `GET /torrents/storage`,
`state.pending: true`; итог читается тем же `GET`.

**Источники:** контракт выбран самим проектом поверх RPC выше; поля Transmission — по ссылкам в предыдущих разделах.
