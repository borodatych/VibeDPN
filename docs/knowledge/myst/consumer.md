# Mysterium consumer: ответы на вопросы §10 idea.md

## [провайдер] Flow consumer через TequilAPI в node 1.39.5

**Контекст:** Stage 8, пункт 1 — «обязательно уточнить» из `docs/idea.md` §10; ответы сняты по исходникам тега 1.39.5, 2026-09-13.
**Identity:** `POST /identities` с `{"passphrase": "..."}` — поле обязательно, пустая строка допустима; `PUT /identities/{id}/unlock` с тем же `passphrase`; список — `GET /identities`, одна — `GET /identities/{id}` (статус регистрации, баланс).
**Регистрация:** `POST /identities/{id}/register` (тело необязательно: `fee`, `beneficiary`, `referral_token`). Уже зарегистрирована — 200, в процессе — 422, иначе 202 и транзактор регистрирует в сети. Бесплатно — только если `canRegisterForFree`; право проверяет `GET /transactor/identities/{id}/eligibility` (`{"eligible": bool}`), иначе берётся комиссия транзактора (`GET /transactor/fees`) из баланса.
**Подключение:** `PUT /connection`, обязателен только `consumer_id`; `provider_id` или `filter.country_code` (и `ip_type`, `sort_by`) выбирают предложение, `service_type` по умолчанию `openvpn` (есть `wireguard`). Не зарегистрированная identity — 422 «not registered», регистрация в процессе — соединение идёт дальше. Статус — `GET /connection`, трафик — `GET /connection/statistics`, разрыв — `DELETE /connection`.
**Kill-switch — ловушка имени:** `connect_options.kill_switch` в JSON — это поле `DisableKillSwitch` (`getConnectOptions` передаёт его как есть). `"kill_switch": true` **выключает** kill-switch ноды; чтобы он работал, поле не передаётся или `false`. Для VibeDPN kill-switch держит и сам роутер коробки (маршрут `unreachable` таблицы `dpn`).
**Предложения:** `GET /proposals?country=DE&service_type=wireguard` (ещё `ip_type`, `quality_min`, `nat_compatibility`, `provider_id`); у предложения `location.country`, `price.per_hour_tokens`, `price.per_gib_tokens`, `quality`.
**Оплата и баланс:** перед соединением `Validator` требует разблокированную identity и, если у предложения цена за час или за ГиБ больше нуля, баланс не меньше цены минуты и цены МиБ. При нулевой цене баланс не проверяется.
**Бесплатно через свою ноду:** цену ставит provider флагами `payment.price-gib` (по умолчанию 0.1) и `payment.price-hour` (0.00006). Нулевая цена действует для всех потребителей сети, а не только для своего consumer, — «бесплатный выход через свою ноду» значит раздавать ноду бесплатно всем. Запрета соединяться со своей нодой в менеджере соединений не нашлось, но и явной поддержки тоже — **не проверено**.
**Контейнер без `--net host`:** официальная Docker-инструкция даёт только `--cap-add NET_ADMIN` и том `/var/lib/mysterium-node` и ничего не говорит о consumer, `/dev/net/tun` и host-сети. Compose коробки даёт consumer `NET_ADMIN`, `/dev/net/tun` и `ip_forward=1` — проверяется запуском в пункте «gateway-контейнер».
**Образ:** `mysteriumnetwork/myst:1.39.5-alpine` — официальный мультиарх-манифест amd64, arm (v7), arm64 (`docker manifest inspect`), свой образ не нужен.
**Каталоги и обновление:** каталог данных — флаг `--data-dir` (`config/flags_directory.go`), в образе `/var/lib/mysterium-node`. Флагов автообновления в `config/flags_*.go` тега нет: версию задаёт тег образа.
**Источники:** https://github.com/mysteriumnetwork/node/blob/1.39.5/tequilapi/endpoints/identities.go ,
https://github.com/mysteriumnetwork/node/blob/1.39.5/tequilapi/contract/identity.go ,
https://github.com/mysteriumnetwork/node/blob/1.39.5/tequilapi/endpoints/transactor.go ,
https://github.com/mysteriumnetwork/node/blob/1.39.5/tequilapi/endpoints/connection.go ,
https://github.com/mysteriumnetwork/node/blob/1.39.5/tequilapi/contract/connection.go ,
https://github.com/mysteriumnetwork/node/blob/1.39.5/tequilapi/endpoints/proposals.go ,
https://github.com/mysteriumnetwork/node/blob/1.39.5/core/connection/connection_validator.go ,
https://github.com/mysteriumnetwork/node/blob/1.39.5/config/flags_service_start.go ,
https://github.com/mysteriumnetwork/node/blob/1.39.5/config/flags_directory.go ,
https://help.mystnodes.com/en/articles/3777670-running-a-mystnodes-as-docker-image-on-linux-host .
