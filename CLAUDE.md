# CLAUDE.md — VibeDPN

Базовые правила — в глобальном `~/.claude/CLAUDE.md`. Здесь — только специфика VibeDPN.

## Что это

Open-source «DPN-коробка» на своём железе: Mysterium-нода (provider), приватный WireGuard-туннель к
своей VPS, consumer-выход через сеть Mysterium, LAN-роутер с политиками и AdGuard Home — одной
кодовой базой в трёх ролях `home` / `vps` / `client`. Концепт и архитектура —
[docs/idea.md](docs/idea.md), план — [docs/roadmap.md](docs/roadmap.md), роли —
[docs/roles.md](docs/roles.md), формат конфига — [docs/manuals/configSpec.md](docs/manuals/configSpec.md).

## Порядок работы

Один чекбокс [roadmap.md](docs/roadmap.md) — одна итерация; стадия закрыта, когда прошли её проверки.
Полный список правил проекта — [.vibe/rules/vibedpn.mdc](.vibe/rules/vibedpn.mdc).

## Красные линии

- **Сеть хоста меняет только `core/vibedpn/engine/router.py`** из шаблонов, идемпотентно. Никаких
  `nft`/`iptables` руками в скриптах.
- **Default route хоста не трогать никогда.** Каждый аплинк — отдельный gateway-контейнер.
- **Внешние факты (myst, AdGuard, WireGuard, Compose) — только из документации с URL** в коммите
  и в `docs/knowledge/`. Память не источник.
- **Секреты не коммитятся**; `config.example.yaml` и `.env.example` соответствуют коду.

## Проверки перед завершением задачи

```bash
(cd core && uv sync --locked && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest) && docker compose --profile '*' config -q && git ls-files -z '*.sh' | xargs -0 shellcheck && actionlint
```

Панель (`ui/`): `(cd ui && bun run check && bun run test:unit && bun run test:dom)`.
Плюс сборка образов, если менялись Dockerfile или зависимости: `docker compose --profile '*' build`.
Инструменты и что они проверяют — [docs/manuals/devSetup.md](docs/manuals/devSetup.md). Тесты не
запускать при ошибках типов — сначала чинить mypy.
