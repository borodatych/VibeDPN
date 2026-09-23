# Когда Docker проверяет здоровье контейнера

## [опыт] Долгий `interval` не задерживает первую проверку, если задан `start_period`

**Контекст:** контейнер `access` (сервер доступа, 2026-09-23): проверка здоровья — настоящее соединение через REALITY, поэтому `interval: 60s`; стенд `router.sh` ждёт `healthy` после `vibedpn up`.
Соблазн — дописать `start_interval: 5s`, чтобы не ждать минуту до первой проверки.

**Как на деле:** пока идёт `start_period`, движок проверяет раз в `start_interval`, а его умолчание — 5 секунд.
В исходнике демона `startInterval := timeoutWithDefault(c.Config.Healthcheck.StartInterval, defaultStartInterval)`, `defaultStartInterval = 5 * time.Second`; справочник Dockerfile даёт то же умолчание и требует Docker Engine 25.0 и новее.
Compose передаёт настройки как есть и умолчания у него те же, что у `HEALTHCHECK`.
Замер на Docker 29.5.2 (colima): `docker run --health-cmd true --health-interval 60s --health-start-period 30s` без `--health-start-interval` стал `healthy` через 5 секунд, в `.Config.Healthcheck` поля `StartInterval` нет.

**Как применять:**
- медленной проверке — длинный `interval` и `start_period` на время запуска; `start_interval: 5s` не писать — это умолчание;
- без `start_period` (умолчание 0) первая проверка ждёт полный `interval`;
- `start_interval` появился в Docker Engine 25.0; как ведут себя старые версии, не проверено.

**Источники:** https://docs.docker.com/reference/dockerfile/#healthcheck (`--start-interval`, умолчание 5s, Engine 25.0); https://docs.docker.com/reference/compose-file/services/#healthcheck (те же умолчания, что у `HEALTHCHECK`); https://github.com/moby/moby/blob/master/daemon/health.go (`defaultStartInterval`, функция `monitor`).
