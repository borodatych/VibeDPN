# Фронтенд-тулчейн (для Stage 6)

> **Устарело 2026-09-13:** замысел React SPA + Vite + nginx заменён решением владельца «UI на start0»
> (2026-09-12). План вариантов — `docs/uiVariants.md`, сборка и память — [start0Build.md](start0Build.md).
> Запись оставлена как история версий на 2026-09-11.

## [провайдер] Версии и две ловушки: TypeScript 7 и oxlint в шаблоне Vite

**Контекст:** UI появится в Stage 6; версии зафиксированы в Stage 0, чтобы техспека не врала.
**Суть (2026-09-11):** react/react-dom 19.3.0, vite 8.3.0 (Node ≥ 20.19 / 22.12),
@vitejs/plugin-react 6.1.1 (peer vite ^8), tailwindcss 4.3.3 (плагин `@tailwindcss/vite`,
`@import "tailwindcss"`), zustand 5.0.15, eslint 10.10.0 (только flat config), typescript-eslint 8.70.0,
eslint-plugin-react-hooks 7.1.1 (`configs.flat.recommended`), shadcn/ui поддерживает Tailwind v4 и
React 19 (`npx shadcn@latest init -t vite`). **Ловушка 1:** npm `latest` TypeScript — 7.0.2, но
typescript-eslint 8.70 держит peer `typescript >=4.8.4 <6.1.0`, а шаблон Vite пинит `~6.0.2` — брать
TypeScript 6.0.x. **Ловушка 2:** шаблон `react-ts` больше не генерирует `eslint.config.js` — он
кладёт `.oxlintrc.json` и `oxlint`; ESLint-конфиг придётся написать руками (Stage 6 решает, ESLint
или oxlint; CI-задача `ui` зовёт нейтральный `npm run lint`). Node: 24 — Active LTS до 2026-10-20,
затем 26; образ для сборки `node:24-alpine`. nginx: mainline `nginx:1.31-alpine` (NGINX рекомендует
mainline для продакшена), stable — 1.30.
**Источники:** https://registry.npmjs.org/react/latest , https://registry.npmjs.org/vite/latest ,
https://registry.npmjs.org/typescript/latest , https://registry.npmjs.org/typescript-eslint/latest ,
https://registry.npmjs.org/eslint/latest , https://registry.npmjs.org/tailwindcss/latest ,
https://ui.shadcn.com/docs/installation/vite , https://vite.dev/guide/ ,
https://typescript-eslint.io/users/configs/ , https://raw.githubusercontent.com/nodejs/Release/main/README.md ,
https://hub.docker.com/_/nginx , https://hub.docker.com/_/node .
