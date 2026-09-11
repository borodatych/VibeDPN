# YAML: `off` и `NO` как булевы

## [баг] PyYAML читает `routing.mode: off` как `false`

**Контекст:** тест `config.example.yaml` упал на первой же итерации: `routing.mode` получил
`False` вместо `"off"`. Тот же эффект у `country: NO` (Норвегия), `yes`, `on`, `y`, `n`.
**Суть:** PyYAML реализует YAML 1.1, где эти слова — булевы литералы. В YAML 1.2 (core schema)
булевы только `true`/`false`, остальное — строки. Загрузчик выбран по этому признаку:
`ruamel.yaml` с `YAML(typ="safe", pure=True)` — YAML 1.2, типизирован (`py.typed`), и в режиме
round-trip умеет переписывать файл с сохранением комментариев — это понадобится командам
`vibedpn mode|upstream|device`, которые правят `config.yaml`, не убивая пояснения пользователя.
`pure=True` закрепляет чисто-питоновый парсер, чтобы поведение не зависело от опционального
C-расширения.
**Применение:** любой YAML в проекте (config.yaml, будущие рендеры конфигов AdGuard) — только
через `vibedpn.config.parse_yaml`. Кавычки вокруг `off`/`NO` в примерах не нужны и не должны
появляться «на всякий случай»: они маскируют выбор загрузчика.
**Источники:** https://yaml.org/spec/1.2.2/#1032-json-schema (булевы в 1.2 — только true/false),
https://yaml.org/type/bool.html (набор булевых литералов 1.1), https://yaml.readthedocs.io/
(ruamel.yaml: `typ='safe'`, `pure`).
