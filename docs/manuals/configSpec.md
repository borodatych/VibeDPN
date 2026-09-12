# Спека `config.yaml`

> **Скопируйте этот файл целиком своей LLM и попросите: «собери config.yaml VibeDPN для …»**
> (например, «для домашней коробки с нодой и выходом через Германию» или «для VPS»). Документ
> самодостаточен: модели не нужны ни исходники, ни интернет.
>
> Канонический источник схемы — `core/vibedpn/config.py`. Здесь она изложена человеческим языком,
> а каждый полный пример ниже прогоняется через модель тестом `core/tests/test_examples.py`:
> разошлись — тест красный.

## Что это за файл

- **Где лежит:** `/opt/vibedpn/config.yaml`. Пишет `vibedpn init`; править руками можно, после
  правки — `vibedpn restart`.
- **Формат:** YAML 1.2 (`off`, `no`, `yes` — строки, не булевы), UTF-8. Ключи — только те, что описаны ниже: **неизвестный ключ — ошибка**,
  опечатка не пройдёт молча.
- **Секретов в нём нет.** Ключи WireGuard, keystore ноды, пароль UI живут в `secrets/`, `data/`
  и `.env` (`chmod 600`). Файл можно показывать при разборе проблемы.
- Первая строка всегда `version: 1` — версия схемы.

## Роли: что обязательно, что запрещено

Роль задаёт, какие секции нужны. Всё, что не подходит роли, — ошибка, а не «игнорируется».

| Секция | `home` (всё в одной коробке) | `vps` (нода + сервер туннеля) | `client` (дом, пара к VPS) |
|---|---|---|---|
| `network` | обязательна | **запрещена** | обязательна |
| `routing` | обязательна | **запрещена** | обязательна |
| `devices` | можно | **запрещена** | можно |
| `upstreams.vps` | **запрещено включать** | **запрещена** | обязательно `enabled: true` (peer-файл — `secrets/wg-client.conf`) |
| `upstreams.dpn` | можно | **запрещена** | можно |
| `provider` | можно (обычно включён) | обязательно `enabled: true` | **запрещено включать** |
| `wg_server` | **запрещена** | обязательна | **запрещена** |
| `dns`, `ui` | можно (по умолчанию включены) | **запрещены** | можно (по умолчанию включены) |
| `firewall` | **запрещена** | можно (по умолчанию включён) | **запрещена** |
| `api` | можно | можно | можно |

## Секции

### `version`

Целое, всегда `1`.

### `role`

`home` | `vps` | `client`. Смысл ролей — в [roles.md](../roles.md).

### `network` — где стоит коробка

| Ключ | Тип | По умолчанию | Смысл |
|---|---|---|---|
| `mode` | `sidecar` \| `gateway` | `sidecar` | `sidecar` — коробка стоит в существующей LAN одним портом; `gateway` — «в разрыв», WAN + LAN двумя портами |
| `lan_interface` | имя интерфейса (`eth0`, `end0`, `enp1s0`; до 15 символов) | — | интерфейс в сторону домашних устройств |
| `lan_subnet` | IPv4-сеть в CIDR (`192.168.1.0/24`) | — | адрес сети, не хоста: `192.168.1.5/24` — ошибка |
| `lan_address` | IPv4 внутри `lan_subnet` | — | адрес коробки в LAN; на нём слушают `ui` и `dns`. Закрепить на роутере (DHCP-резервация или статика) |
| `wan_interface` | имя интерфейса | — | только для `mode: gateway`, обязателен там и запрещён в `sidecar`; не равен `lan_interface` |

### `routing` — политика LAN-трафика

| Ключ | Тип | По умолчанию | Смысл |
|---|---|---|---|
| `mode` | `off` \| `full` \| `smart` | `off` | `off` — всё напрямую; `full` — всё через `default_upstream`, кроме устройств с политикой; `smart` — через аплинк только `smart_domains` и устройства с политикой |
| `default_upstream` | `vps` \| `dpn` | — (обязателен) | куда идёт трафик в `full`/`smart`. Если `mode` не `off`, аплинк должен быть включён в `upstreams`. У `home` бывает только `dpn` |
| `failopen` | bool | `false` | `false` — упал аплинк, трафик устройств с политикой `vps`/`dpn` стоит (kill-switch); `true` — уходит напрямую, осознанный выбор |
| `smart_domains` | список доменных суффиксов | `[]` | для `mode: smart`; `netflix.com` покрывает и поддомены. Приводятся к нижнему регистру, дубликаты — ошибка |

### `devices` — устройства с собственной политикой

Список; каждый элемент:

| Ключ | Тип | Смысл |
|---|---|---|
| `name` | строка 1–64 | как показывать в UI |
| `mac` | `aa:bb:cc:dd:ee:ff` (регистр и `-` не важны) | основной идентификатор |
| `ip` | IPv4 | запасной идентификатор; нужен хотя бы один из `mac`/`ip` |
| `policy` | `vps` \| `dpn` \| `bypass` \| `block` | поверх `routing.mode`. `vps`/`dpn` требуют включённого аплинка |

Один и тот же `mac` или `ip` дважды — ошибка.

### `upstreams` — аплинки

```yaml
upstreams:
  vps:
    enabled: true                    # peer-файл лежит в secrets/wg-client.conf, в конфиге его нет
  dpn:
    enabled: true
    country: DE                      # ISO 3166-1 alpha-2; нет строки — любая страна
```

- `vps` — приватный WireGuard-туннель к своей VPS (контейнер `wg-client`). Только роль `client`.
  Peer-файл от `vibedpn peer export` на VPS `init --peer-config` кладёт в `secrets/wg-client.conf`;
  путь фиксированный, поэтому в конфиге не упоминается.
- `dpn` — consumer Mysterium: выход через ноду сети. `country` — двухбуквенный код, регистр не
  важен; кавычки не нужны (`NO` — Норвегия, файл читается как YAML 1.2, где это строка).

### `provider` — нода Mysterium

| Ключ | Тип | По умолчанию | Смысл |
|---|---|---|---|
| `enabled` | bool | `false` | раздавать канал и получать MYST |
| `udp_ports` | `"start-end"` | `"56000-56100"` | UDP-диапазон ноды (флаг `--udp.ports`); пробрасывать на роутере |
| `traversal` | список из `manual`, `upnp`, `holepunching` | `[manual, upnp, holepunching]` | порядок обхода NAT (флаг `--traversal`): проброс руками, UPnP, hole punching. Минимум один, без повторов |

Диапазон — строка в кавычках, 1–65535, `start <= end`.

### `wg_server` — сервер приватного туннеля (только `vps`)

| Ключ | Тип | По умолчанию | Смысл |
|---|---|---|---|
| `endpoint` | hostname или IPv4 | — (обязателен) | что домашние коробки набирают: публичный адрес VPS |
| `subnet` | IPv4-сеть | `10.78.0.0/24` | адреса туннеля; сервер берёт первый, минимум `/30` |
| `listen_port` | 1–65535 | `51820` | UDP-порт сервера |

### `dns` — AdGuard Home

| Ключ | Тип | По умолчанию | Смысл |
|---|---|---|---|
| `enabled` | bool | `true` | DNS и адблок на порту 53 LAN-интерфейса |
| `upstreams` | список URL `https://…` | `[https://dns.cloudflare.com/dns-query]` | апстримы DNS-over-HTTPS; минимум один |
| `web_port` | 1–65535 | `3000` | веб-панель AdGuard на LAN-интерфейсе |

### `ui` — веб-интерфейс коробки

| Ключ | Тип | По умолчанию |
|---|---|---|
| `enabled` | bool | `true` |
| `port` | 1–65535 | `80` |

Слушает только LAN-интерфейс и проксирует API ядра с авторизацией.

### `firewall` — файрвол VPS (только `vps`)

nftables-таблица `inet vibedpn`, на вход всё закрыто, кроме: ssh, порта `wg_server`, UDP-диапазона
ноды, трафика из туннеля `wg0`, ICMP и перечисленного ниже. `core` применяет её при каждом старте.

| Ключ | Тип | По умолчанию | Смысл |
|---|---|---|---|
| `enabled` | bool | `true` | выключить — `core` при старте снимает таблицу, VPS остаётся с тем, что настроил хостер (`vibedpn down` таблицу не снимает) |
| `ssh_ports` | список портов | `[22]` | `init` берёт порты у самого демона (`sshd -T`: `port` и `listenaddress host:port`), без него — из `sshd_config` и `Include` (все `Port`, `ListenAddress` с портом, разделители как у sshd: пробел, таб или `=`); пустой список — ошибка, чтобы не запереть себя; `doctor` сверяет список с реальными портами sshd |
| `allow_tcp` | список портов | `[]` | другие TCP-сервисы владельца на этой же VPS |
| `allow_udp` | список портов | `[]` | другие UDP-сервисы владельца |

### `api` — API ядра

| Ключ | Тип | По умолчанию |
|---|---|---|
| `port` | 1–65535 | `4480` |

Ядро слушает только `127.0.0.1`; на LAN его отдаёт `ui`, на VPS — через wg0.

## Полные примеры

Каждый блок — законченный валидный конфиг (первая строка `# example: …` — метка для теста).

### `home` — всё в одной коробке

```yaml
# example: home
version: 1
role: home
network:
  mode: sidecar
  lan_interface: eth0
  lan_subnet: 192.168.1.0/24
  lan_address: 192.168.1.50
routing:
  mode: full
  default_upstream: dpn
  failopen: false
  smart_domains: []
devices:
  - name: TV
    mac: aa:bb:cc:dd:ee:01
    policy: bypass
  - name: Work laptop
    ip: 192.168.1.42
    policy: block
upstreams:
  dpn:
    enabled: true
    country: DE
provider:
  enabled: true
  udp_ports: "56000-56100"
  traversal: [manual, upnp, holepunching]
dns:
  enabled: true
  upstreams:
    - https://dns.cloudflare.com/dns-query
  web_port: 3000
ui:
  enabled: true
  port: 80
api:
  port: 4480
```

### `vps` — нода и сервер туннеля, без LAN

```yaml
# example: vps
version: 1
role: vps
provider:
  enabled: true
  udp_ports: "56000-56100"
  traversal: [manual, upnp, holepunching]
wg_server:
  endpoint: 203.0.113.7
  subnet: 10.78.0.0/24
  listen_port: 51820
firewall:
  enabled: true
  ssh_ports: [22]
  allow_tcp: []
  allow_udp: []
api:
  port: 4480
```

### `client` — дома, в паре с VPS

```yaml
# example: client
version: 1
role: client
network:
  mode: sidecar
  lan_interface: end0
  lan_subnet: 192.168.0.0/24
  lan_address: 192.168.0.2
routing:
  mode: full
  default_upstream: vps
  failopen: false
upstreams:
  vps:
    enabled: true
  dpn:
    enabled: false
dns:
  enabled: true
ui:
  enabled: true
```

## Как из конфига получается `.env`

`vibedpn init` пишет `.env` для `compose.yaml`; всё в нём, кроме `VIBEDPN_TAG`, — производные
от этого файла (`Config.env_vars()`), руками их не править: `COMPOSE_PROFILES`, `VIBEDPN_API_PORT`,
`VIBEDPN_LAN_IP` и `VIBEDPN_UI_PORT` (роли с LAN), `VIBEDPN_MYST_UDP_FROM/TO` и
`VIBEDPN_MYST_TRAVERSAL` (если включён provider).

| Роль | Профили |
|---|---|
| `home` | `provider` (если `provider.enabled`), `consumer` (если `upstreams.dpn.enabled`), `router`, `dns` (если `dns.enabled`), `ui` (если `ui.enabled`) |
| `vps` | `provider`, `wg-server` |
| `client` | `consumer` (если `upstreams.dpn.enabled`), `wg-client`, `router`, `dns`, `ui` (по включённости) |

Порядок в строке всегда канонический: `provider, consumer, wg-server, wg-client, router, dns, ui`.
