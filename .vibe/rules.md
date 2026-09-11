# Правила проекта для агента

Базовые правила — в `CLAUDE.md` в корне (указатель на глобальные) и в `.vibe/rules/vibedpn.mdc`.

- **Стек:** хост Debian 12/13 или Raspberry Pi OS 64-bit; Docker Compose v2 с профилями;
  `core/` — Python 3.12 (FastAPI, Pydantic v2, Typer), пакет `vibedpn`, менеджер `uv`;
  `images/wg/` — Alpine + wireguard-tools + nftables; `ui/` — React + TypeScript strict + Vite.
- **Проверки:** см. `CLAUDE.md`, раздел «Проверки перед завершением задачи».
- **Комментарии в коде — на английском**, документация и коммиты — на русском.
- **Сеть хоста** меняет только `core/vibedpn/engine/router.py` из шаблонов; default route хоста
  не трогать никогда.
