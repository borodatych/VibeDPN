# Панель ноды и API ядра через туннель

## [архитектура] Слушатели ядра на адресе туннеля: `IP_FREEBIND`, проброс NodeUI, файрвол

**Контекст:** Stage 3, чекбокс 4 — NodeUI 4449 и API ядра доступны с домашней стороны через wg0
и больше ниоткуда.
**Суть:** на роли vps ядро (host network) слушает, кроме loopback, адрес сервера туннеля —
первый хост `wg_server.subnet`. На `api.port` там отвечает то же приложение, но за шлюзом ASGI:
только `GET /health` и `GET /provider/stats` и только для клиентов из подсети туннеля; управление
пирами и выгрузка их файлов через туннель недоступны — иначе любая коробка забрала бы чужие ключи.
На 4449 — побайтовый TCP-проброс на `127.0.0.1:4449`, куда compose публикует панель ноды;
TequilAPI (4050) через туннель не выходит. Чужой адрес получает обрыв соединения; подделать адрес
туннеля нельзя — ответ на TCP-handshake уходит в wg0, а не подделывающему.
**`IP_FREEBIND`:** ядро стартует раньше `wg-server` (тот ждёт здорового ядра), а `wg0`
пропадает при каждом его перезапуске. Опция сокета `IP_FREEBIND` (значение 15 в
`<linux/in.h>`; в модуле `socket` Python 3.12 константы нет) разрешает привязку к адресу, которого
на машине ещё нет. Проверено исполнением: без опции `bind` падает с «Cannot assign requested
address»; с опцией слушатель молчит, пока адреса нет, отвечает, когда адрес появился, молчит, пока
интерфейс удалён, и снова отвечает после его пересоздания — перепривязывать ничего не нужно.
Только Linux: на macOS опции нет, тест пропускается.
**Несколько uvicorn в одном процессе:** `Server.serve` оборачивает работу в `capture_signals`,
который ставит обработчики через `signal.signal` на каждый сервер; второй сервер молча заменил бы
обработчики первого, и по SIGTERM погас бы только один. Серверы ядра — наследники с пустым
`capture_signals`, а процесс ставит один обработчик на цикл событий, который останавливает все
серверы и проброс. Заранее созданные сокеты uvicorn 0.52 принимает через `serve(sockets=[...])`.
**NodeUI за пробросом:** у TequilAPI фильтр заголовка `Host` пропускает любой IP-литерал, а
обратный прокси NodeUI сам переписывает `Host` на `127.0.0.1:<порт TequilAPI>`. Фильтр «только
localhost» смотрит на адрес клиента с доверенным прокси `127.0.0.1`; при доступе через
опубликованный порт нода и так видит адрес шлюза Docker. Проброс ядра подключается к тому же
`127.0.0.1:4449`, поэтому панель через туннель ведёт себя ровно как при локальном доступе.
**Файрвол VPS:** вместо «с `wg0` всё» — только порты панели и API; первым делом после `lo`
отбрасываются пакеты к подсети туннеля, пришедшие не через `wg0` (`ip daddr <подсеть> iifname !=
"wg0" drop`), — сосед по L2 не доберётся до слушателей, подставив маршрут. Правила проверены
`nft -c` и двойным применением в контейнере с NET_ADMIN.
**Сброс вместо EOF:** проброс закрывает соединение чужого клиента, не читая его запрос; если
запрос уже пришёл, ядро Linux и macOS отвечает RST, и клиент видит «Connection reset», а не пустой
ответ. Для отказа это правильно, тест принимает оба исхода.
**Применение:** `core/vibedpn/api/tunnel.py` (`listen_socket`, `TunnelGate`, `relay`, `serve`),
`core/vibedpn/templates/firewall.nft.j2`, `core/vibedpn/doctor.py` («tunnel access»).
**Источники:** https://raw.githubusercontent.com/torvalds/linux/master/include/uapi/linux/in.h
(`IP_FREEBIND 15`), https://man7.org/linux/man-pages/man7/ip.7.html (ссылка на `IP_FREEBIND`),
https://github.com/encode/uvicorn/blob/master/uvicorn/server.py (`serve`, `capture_signals`),
https://github.com/mysteriumnetwork/node/blob/master/tequilapi/middlewares/http_middlewares.go
(`NewHostFilter`, `NewLocalhostOnlyFilter`),
https://github.com/mysteriumnetwork/node/blob/master/tequilapi/http_api_server.go
(`SetTrustedProxies`), https://github.com/mysteriumnetwork/node/blob/master/ui/ui_reverse_proxy.go
(переписывание `Host`); исполнение 2026-09-12.
