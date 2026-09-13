# start0 на коробке: сборка, память, Bun на ARMv8.0

## [платформа] UI не собирается на коробке, а работающий стоит ~360 МиБ

**Контекст:** Stage 6, план двух вариантов UI (`docs/uiVariants.md`), 2026-09-13.
**Суть:** `docker build` пака start0 v0.1.23 на VM colima (aarch64, 2 ГиБ) упал на `bun run build` через 988 с с *ResourceExhausted … cannot allocate memory*.
Та же сборка нативно заняла 79 с при пике RSS 2.18 ГиБ (`/usr/bin/time -l`).
Вывод: коробки получают готовые образы из CI, сборка на хосте не предусматривается.
**Замер runtime (образ из готового `dist`, arm64, 469 МБ):**
- приложение — 205 МиБ в простое, 283 МиБ после 600 запросов;
- `postgres:17-alpine` — 69–78 МиБ;
- старт сервера — 290 мс.
**Привязка к Postgres:** `@prisma/adapter-pg`, очередь `pg-boss` (`modules/worker`, пользуются только `modules/health/worker.ts` и `modules/axiom/provision.ts`), backplane сокетов на LISTEN/NOTIFY (`lib/backplane.ts`).
SQLite ради Pi не рассматривается.
**Bun на Raspberry Pi 4:** Bun до 1.3.9 падал с *Illegal instruction* на ARMv8.0 (Cortex-A72, A53).
Причина — инструкции LSE atomics из mimalloc и WebKit.
Исправлено в PR #26586 (влит 2026-01-30, `MI_NO_OPT_ARCH=ON`, WebKit с явным `-march`, проверка под QEMU).
Мейнтейнер закрыл issue #26556 словами *Fixed in Bun v1.3.9*.
Пак требует `bun ^1.3.14`, `oven/bun:1` на 2026-09-13 — 1.4.2.
На живом Pi 4 не проверено.
**Источники:** https://github.com/oven-sh/bun/issues/26556 , https://github.com/oven-sh/bun/pull/26586 ,
https://github.com/oven-sh/bun/pull/26545 (закрыт без слияния — базовая сборка ARM64 не понадобилась).

## [архитектура] Вход в панель паролем коробки без копии пароля в базе

**Контекст:** Stage 6, каркас панели (`ui/src/modules/auth/box-password.ts`), 2026-09-13.
**Суть:** `vibedpn init` хранит только bcrypt (`secrets/htpasswd`), открытого пароля нигде нет.
better-auth позволяет заменить `emailAndPassword.password.hash` и `verify`: `hash` отдаёт маркер, `verify` принимает только аккаунт с маркером и сверяет пароль с bcrypt-строкой `admin`.
`Bun.password.verify` проверяет `$2b$` из Python bcrypt (исполнением: верный — `true`, чужой — `false`); по документации Bun определяет алгоритм по самому хешу.
Файл читается на каждом входе: смена пароля через `init --force` действует без перезапуска панели.
**Грабли:**
- Пак сам занимает `/api/auth/*` и `/api/health`, поэтому прежнее правило nginx «`/api/` → ядро» с ним несовместимо: ядро переехало под `/api/core/*`, middleware Point0 по пути (документация Point0, раздел middleware) проверяет сессию и проксирует на `127.0.0.1`.
- Point0 разворачивает `bunServeConfig` в `Bun.serve`, а у Bun `hostname` по умолчанию `0.0.0.0`: без явного адреса панель слушала бы все интерфейсы, включая WAN.
- Rate limit better-auth по умолчанию выключен в development; включён явно. Встроенное правило `/sign-in/email` — 3 запроса за 10 с (до ~1000 паролей в час); своё — 5 за 300 с (`customRules`).
- **Подмена адреса обходила лимит (исправлено 2026-09-13).** better-auth берёт IP только из заголовков (по умолчанию `x-forwarded-for`), а прокси перед панелью нет: шесть неверных паролей подряд с новым `X-Forwarded-For` — все 401, без заголовка — 429. Point0 знает адрес сокета (`request.from.ip` = `bunServer.requestIP`), поэтому middleware `/api/auth/*` удаляет пересылочные заголовки и ставит `x-vibedpn-client-ip`, а `advanced.ipAddress.ipAddressHeaders` читает только его. После правки: 429 при подмене `X-Forwarded-For` и `X-Real-IP`.
- `trustedOrigins` было `[CLIENT_URL]`: вход со страницы, открытой по имени, давал 403 *Invalid origin*. Теперь — адрес и `ui.host_name` на той же схеме и порту (`UI_HOST_NAME`). Порт 80 в `CLIENT_URL` не мешает: Origin без порта принимается (проверено исполнением).
- Cookie без `Secure`: у панели HTTP в LAN, `useSecureCookies: false` явно, `SameSite=Strict` через `advanced.cookies.session_token.attributes`.
- `bun install --ignore-scripts` в Dockerfile ломает сборку: `point0 build` падает с *Error: Bun's postinstall script was not run.* (первый прогон `ui-image`, воспроизведено в чистой копии). Скрипты зависимостей остаются включены; Bun и так запускает их только у доверенных пакетов.
- `secrets/ui-db-password` пишется без перевода строки: он собирается в `DATABASE_URL`, а при смене пароль базы разошёлся бы с томом `data/ui-db` — поэтому `init` не перетирает эти секреты.
**Источники:** https://www.better-auth.com/docs/authentication/email-password ,
https://www.better-auth.com/docs/concepts/rate-limit , https://www.better-auth.com/docs/concepts/cookies ,
https://www.better-auth.com/docs/reference/options (`trustedOrigins`, `advanced.ipAddress`),
https://bun.com/docs/runtime/hashing , https://bun.com/docs/runtime/http/server ,
https://hub.docker.com/_/postgres (`POSTGRES_PASSWORD_FILE`, `/var/lib/postgresql/data`).
