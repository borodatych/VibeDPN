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
