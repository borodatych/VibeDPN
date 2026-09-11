# Документация VibeDPN

```
docs/
├── idea.md               # концепт и архитектура — исходный kickoff-промпт
├── roadmap.md            # план по стадиям, один чекбокс — одна итерация
├── roles.md              # роли home / vps / client, профили Compose и контейнеры
├── functional.md         # каталог возможностей продукта (что уже умеет)
├── techSpec.md           # живая техспека: стек, версии, образы, сервисы, файлы на коробке
├── manuals/              # руководства «как сделать» по шагам и спеки форматов
│   ├── configSpec.md     # формат config.yaml — можно скормить модели целиком
│   └── devSetup.md       # локальная среда разработки и все проверки
└── knowledge/            # база знаний: грабли и проверенные факты с URL
    ├── README.md         # индекс — запись без строки здесь не существует
    ├── myst/  adguard/  compose/  docker/  wireguard/  platform/  ci/  frontend/
    ├── python/
    └── process/
```

Имена файлов и папок в `docs/` — camelCase. Исключения только для общепринятых верхнеуровневых
имён: `README.md`, `roadmap.md`, `functional.md`, `idea.md`.

## Соответствие путям из kickoff-промпта

Kickoff ([idea.md](idea.md), §5 и §12) называл документы по-своему; в репозитории они лежат по
соглашениям проекта:

| В kickoff | В репозитории |
|---|---|
| `ROADMAP.md` (корень) | [roadmap.md](roadmap.md) |
| `docs/README.ru.md` («для друзей») | [../README.md](../README.md) — репозиторий русскоязычный, сценарии живут в главном README; каталог возможностей — [functional.md](functional.md) |
| `docs/ROLES.md` | [roles.md](roles.md) |
| `docs/TROUBLESHOOTING.md` | `docs/troubleshooting.md` (появится в Stage 11) |
| `docs/MYST.md` | `docs/knowledge/myst/` (Stage 8) |
| `.vibe/vibedpn.mdc` | `.vibe/rules/vibedpn.mdc` — правила набора живут в `rules/` |
