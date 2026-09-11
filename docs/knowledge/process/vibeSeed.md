# Засев `.vibe/`

## [договорённость] `.vibe/` скопирован из канона VibeBrains, а не написан руками

**Контекст:** kickoff требует «`.vibe/` со стандартным набором + `vibedpn.mdc`». Стандартный
набор — не текст, который пишет агент, а канонический образ из репозитория VibeBrains
(`github.com/VibeBrains/VibeBrains`), который VibeIDE и VibeIDEA сеют в проект при открытии
(create-if-missing, ревизии в `versions.json`).
**Суть:** набор взят из сабмодуля `VibeIDE/.vibe-defaults` на коммите `f1903c5` (2026-09-10) —
он новее локального чекаута VibeBrains (2026-08-29). Не сеются служебные файлы набора
(`versions.json`, `deprecated.json`, `products.json`, `bump.mjs`) и файлы, адресованные только
VibeIDEA по `products.json` (`patrols.json`, `dataSources.json`) — VibeIDEA доложит их сама.
`gitignore.seed` стал `.vibe/.gitignore`. Нетронутые копии продукт при открытии узнает по sha и
будет обновлять молча; правленные (`rules.md`, наш `rules/vibedpn.mdc`) — не трогает.
**Применение:** обновлять набор — не руками, а открытием проекта в VibeIDE/VibeIDEA; править
общие правила — в VibeBrains, не здесь.
