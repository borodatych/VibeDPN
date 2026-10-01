# Код и образы коробки переходят вместе

Источник: https://github.com/docker/metadata-action — `type=sha` даёт тег `sha-<первые 7 знаков коммита>`, а метка `org.opencontainers.image.revision` несёт полный коммит.

## Грабли

- Тег ветки (`next`) сдвигается, когда CI достроит образы, а не когда пришёл коммит
  Обновление в эти 20–40 минут ставит новый код на старые образы: так было 01.10.2026, код `d892612` на образах `92a9e66`
- `install.sh` без цели делает `merge --ff-only origin/<ветка>` — вершину, готовы её образы или нет

## Как устроено

- `vibedpn update` смотрит последние 20 коммитов ветки и берёт самый новый, у которого есть все образы коробки с тегом `sha-…`
- Образы коробки — `docker compose config --images` всех профилей, только `ghcr.io/borodatych/vibedpn-*`; у панели тег с суффиксом варианта: `sha-xxxxxxx-full`
- Наличие — `docker manifest inspect <образ>`: читается манифест, слои не качаются; публичный GHCR отвечает без входа (проверено на коробке, Docker 29.8)
- Цель передаётся `install.sh` как `VIBEDPN_REF`, тег пишется в `.env` как `VIBEDPN_TAG=sha-…`
- Проверить руками: `docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' <образ>` и `git -C /opt/vibedpn rev-parse HEAD`
