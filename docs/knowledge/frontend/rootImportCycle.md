# `bun dev` панели: цикл импортов вокруг `root`

**Контекст:** панель `ui/` на Point0, `bun dev` падал с 2026-09-15 (`7ecac81`, панель на русском), исправлено 2026-09-25.

## [грабли] Точка Point0 в графе импортов `lib/root` читает `root` раньше, чем он есть

`point0 dev` загружает модули ES по одному, и первым сгенерированный `points.server.ts` импортирует `lib/root.tsx`.
`root.tsx` импортирует страницы ошибок, они — переводчик `useT`, а тот брал язык из `languageQuery`.
`languageQuery` строится на верхнем уровне модуля: `root.lets.query()…`, и в этот момент `root` ещё в TDZ.
Итог: `ReferenceError: Cannot access 'root' before initialization` на `modules/i18n/api.ts`.
Продовая сборка работала только потому, что сборщик расставил модули в бандле в удачном порядке.
Воспроизведение одной командой в `ui/` с переменными стенда:
`NODE_ENV=development bun -e "await import('./src/preload.ts'); await import('./src/lib/root.tsx')"`.
Не лечит: провайдер Point0 (`root.lets.provider()`) — он тоже строится от `root` на верхнем уровне; `React.lazy` в страницах ошибок — оставляет цикл в графе и усложняет SSR.
**Решение:** `useT` и `useLanguage` читают React-контекст `LanguageContext` из `modules/i18n/use-t.tsx`, в котором нет ни одной точки Point0.
`LanguageProvider` (`modules/i18n/provider.tsx`) — единственный читатель `languageQuery`, стоит в `App` под `QueryClientProvider`; там же `LanguageSwitcher`.
Вне провайдера (граница ошибок над приложением, тесты) панель говорит на базовом английском, а не падает.
**Гейт:** `ui/src/lib/root.unit.test.ts` обходит импорты `root.tsx` через `Bun.Transpiler.scanImports` и падает на любой цепочке, которая возвращается к `root`.
Импорты только типов стираются и в граф не входят; динамический `import()` тоже не входит — он выполняется из функции, когда `root` уже есть (так `auth/server.ts` берёт `auth/socket`).
Файлы `.ts` читаются загрузчиком `ts`, а `.tsx` — `tsx`: в `.tsx` дженерик `<T>(x) =>` разбирается как тег, и сканер падает с «Unexpected return».
На прежнем коде гейт показывает ровно цепочку `lib/root.tsx → components/other/error.tsx → modules/i18n/use-t.tsx → modules/i18n/api.ts → lib/root.tsx`.
**Проверено:** команда воспроизведения — `ReferenceError` до правки, `root` загружается после; `bun dev` поднимается, `/sign-in` отдаёт 200 и русский текст; продовая сборка до и после отдаёт одну страницу входа (`lang="ru"`, тот же текст), разница — только хеши ресурсов.
Наблюдение без разбора: в `bun dev` та же страница приходит с `<html lang="en">` при русском тексте, в продовой сборке — `lang="ru"`.

## [грабли] `prettier-plugin-jsdoc` склеивает строки описания

Плагин собирает описание JSDoc в абзац по `printWidth` и `proseWrap` при этом не слушает: `preserve` в `overrides` ничего не меняет.
Мысль на строку переживает `bun run format` только отдельным абзацем — с пустой строкой ` *` между мыслями.
`bun run check` prettier не запускает, хук pre-commit у пакета в подкаталоге не ставится — склейка случится при первом ручном `format`.
