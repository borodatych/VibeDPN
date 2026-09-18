# hostapd: проверка конфига без Wi-Fi

## [провайдер] Ошибка конфига и ошибка драйвера различимы по выводу

**Контекст:** Stage 9, точка доступа Wi-Fi как LAN-сторона gateway-режима; у Linux-VM разработки нет Wi-Fi, 2026-09-13.

**Суть (исполнением, hostapd v2.11 из Alpine 3.24, контейнер `alpine:3.24` на colima VM):**
hostapd сначала разбирает весь файл, и только потом поднимает драйвер.

Верный конфиг на несуществующем интерфейсе падает на драйвере:
`nl80211: 'nl80211' generic netlink not found`, затем `Failed to initialize driver 'nl80211'` и `AP-DISABLED`.
Проверенные ключи: `interface`, `driver=nl80211`, `ssid`, `hw_mode=g`, `channel=1`, `country_code`, `wpa=2`, `wpa_key_mgmt=SAE`, `ieee80211w=2`, `wpa_passphrase`, `rsn_pairwise=CCMP`.

Конфиг с неизвестным ключом до драйвера не доходит:
`Line 3: unknown configuration item 'bogus_key'`, затем `1 errors found in configuration file '/tmp/bad.conf'`.

**Как применять:** отрендеренный конфиг проверяется настоящим hostapd без радио.
Строки `errors found in configuration file` быть не должно, а `Failed to initialize driver` означает, что разбор прошёл.
Это проверка формата, а не работы точки доступа.

**Грабля опыта:** в ядре VM `6.8.0-117-generic` (Ubuntu 24.04) нет `mac80211_hwsim` (`modinfo: Module mac80211_hwsim not found`): модуль лежит в пакете `linux-modules-extra-$(uname -r)` (123 МБ).
После установки `modprobe mac80211_hwsim radios=2` даёт `phy0`, `phy1` и интерфейсы `wlan0`, `wlan1` — виртуальное радио для стенда точки доступа.
Откат: `sudo modprobe -r mac80211_hwsim && sudo apt-get remove -y linux-modules-extra-$(uname -r)`.

## [провайдер] Точка доступа WPA3-SAE из контейнера на виртуальном радио

**Суть (исполнением, colima VM, `mac80211_hwsim radios=2`, 2026-09-13):**
hostapd 2.11 в контейнере Alpine 3.24 с `--network host`, `NET_ADMIN` и `NET_RAW` поднял точку доступа на `wlan0` (`AP-ENABLED`).
Второе радио переносится в netns целиком: `iw phy phy1 set netns name wifilab` — интерфейс `wlan1` уезжает вместе с ним.
Клиент в netns видит сеть (`iw dev wlan1 scan`: `SSID: vibedpn-lab`, `Authentication suites: SAE`).
`wpa_supplicant` хоста подключился: `CTRL-EVENT-CONNECTED`; hostapd — `AP-STA-CONNECTED` и `EAPOL-4WAY-HS-COMPLETED`.
Ключи точки доступа: `wpa=2`, `wpa_key_mgmt=SAE`, `ieee80211w=2`, `sae_pwe=2`, `rsn_pairwise=CCMP`.
В сообщении `rfkill: Cannot open RFKILL control device` hostapd в контейнере не нуждается: точка доступа работает и без него.

**Грабля опыта:** у `wpa_supplicant` параметр `sae_pwe` глобальный, а не поле блока `network`.
Внутри блока он даёт `unknown network field 'sae_pwe'` и `failed to parse network block`.

**Источники:** https://w1.fi/cgit/hostap/plain/hostapd/hostapd.conf (описание ключей; страница за защитой Anubis, ключи сверены с примером `/etc/hostapd/hostapd.conf` пакета Alpine и исполнением).

## Пароль WPA-PSK: 8–63 символа ASCII

**Факт:** `wpa_passphrase` — ASCII-пароль длиной от 8 до 63 символов; из него и SSID выводится PSK, поэтому смена SSID меняет и ключ.
Альтернатива — `wpa_psk` из 64 шестнадцатеричных цифр.
**Источник:** пример `/etc/hostapd/hostapd.conf` в образе `vibedpn-hostapd` (hostapd v2.11), раздел «WPA pre-shared keys for WPA-PSK»; оригинал — https://w1.fi/cgit/hostap/plain/hostapd/hostapd.conf (за защитой Anubis), прочитано из контейнера на коробке 2026-09-15.
**Как применено:** `vibedpn wifi passphrase` принимает 8–63 печатных символа ASCII без пробелов по краям (края срезает чтение секрета).

## RTL8852BE (rtw89): телефон выкидывает каждые несколько секунд

**Наблюдение** (N100, Debian 13, ядро 6.12.107, `rtw89_8852be`, hostapd v2.11, 2026-09-15): телефон подключается, проходит 4-way handshake и через 6–60 секунд получает `AP-STA-DISCONNECTED`; в `dmesg` за 1–2 секунды до каждого отключения — `rtw89_8852be: timed out to flush queues`.
Точка была в режиме 802.11g без HT (`iw dev` — `no HT`), `hostapd.conf` без `ieee80211n`, `wmm_enabled` и `disassoc_low_ack`.

**Что не помогло:** выключатели энергосбережения драйвера из `modinfo` — `rtw89_pci disable_aspm_l1=Y disable_aspm_l1ss=Y disable_clkreq=Y`, `rtw89_core disable_ps_mode=Y` (`/etc/modprobe.d/vibedpn-rtw89.conf`, модули перезагружены): ошибки и отключения остались. Файл на коробке оставлен, вреда не замечено.

**Что улучшило, но не решило:** `ieee80211n=1`, `wmm_enabled=1`, `disassoc_low_ack=0` — вместо отключения каждые секунды телефон держал связь минуты (MCS 12, 78 Мбит/с, `tx failed: 0`), но в 10:22:39 UTC выпал снова через секунду после `timed out to flush queues` (05:22:37 по часам коробки); ещё одна такая ошибка — перед подключением в 10:18:31.
Вывод: корень в драйвере `rtw89` в режиме точки доступа, конфиг hostapd только снижает частоту.
**Смысл ключей** — пример `/etc/hostapd/hostapd.conf` в образе (hostapd v2.11): `disassoc_low_ack` — «Disassociate stations based on excessive transmission failures or other indications of connection loss»; `wmm_enabled` — очереди WMM (QoS); `ieee80211n` — режим 802.11n.
**Как применено:** `engine/hostapd.py` пишет эти три строки в каждый `hostapd.conf`; устойчивость точки доступа на этом чипе остаётся открытой.

**Ядро 7.1.8 и свежая прошивка (2026-09-15):** `linux-image-amd64` 7.1.8 из `trixie-backports` просит `rtw89/rtw8852b_fw-2.bin`, которой нет в `firmware-realtek` 20250410 (`failed to load rtw89/rtw8852b_fw-2.bin`, откат на `fw-1`); `firmware-realtek` 20260810 из backports её приносит (`loaded firmware rtw89/rtw8852b_fw-2.bin`).
С ними за полтора часа наблюдения `timed out to flush queues` осталось, но редко: в 11:11:44 и 11:46:04 UTC — и ровно в эти секунды телефон получал `AP-STA-DISCONNECTED`; между ними он держался по 20–30 минут (`tx failed: 0`, MCS 12).
Вывод: новое ядро и прошивка сократили обрывы с раза в несколько минут до раза в полчаса-час, но не устранили; корень — драйвер `rtw89` в режиме точки доступа.

**Откуда сообщение и что известно (исследование 2026-09-15):**
- `timed out to flush queues` печатает `rtw89_mac_flush_txq()` в `drivers/net/wireless/realtek/rtw89/mac.c`, когда буфер передачи в чипе не опустел за 200 мс (опрос раз в 10 мс), сброс идёт без отбрасывания и есть подключённая станция; уровень — info. Вызывается при `DISABLE_KEY` и из колбэка mac80211 `.flush` (`mac80211.c`). Источник: https://github.com/torvalds/linux/blob/master/drivers/net/wireless/realtek/rtw89/mac.c , https://github.com/torvalds/linux/blob/master/drivers/net/wireless/realtek/rtw89/mac80211.c
- Следствие, не проверено: ключи станции снимаются при её отключении, значит сообщение может быть частью отключения, а не его причиной. Проверка — отладочный лог hostapd (`logger_stdout_level=0`) вокруг `AP-STA-DISCONNECTED`.
- Найденные отчёты с этим сообщением — только режим клиента: RTL8852BE https://bbs.archlinux.org/viewtopic.php?pid=2257715 (помог откат `linux-firmware-realtek` или удаление `fw-1.bin`), https://github.com/lwfinger/rtw89/issues/259 (ASPM/CLKREQ не помогли); RTL8852AE https://www.spinics.net/lists/linux-wireless/msg222193.html ; RTL8852CE на 7.1.3 https://ratatoskr.run/linux-wireless/2026/07/17227566/t (сопровождающий Realtek ожидает патчи к 7.3, это про 8852C). Отчётов про AP/hostapd и исправления для 8852B не найдено.
- Режим AP в rtw89 объявлен серией «rtw89: support AP mode» (2022): https://lkml.kernel.org/linux-wireless/20220207063900.43643-8-pkshih@realtek.com/ ; документированных ограничений AP для 8852BE не найдено.

## Отладочный уровень точки доступа стирается перезапуском ядра (2026-09-15)

`logger_stdout=-1` / `logger_stdout_level=0` в `/opt/vibedpn/data/hostapd/hostapd.conf` живут ровно до следующего `vibedpn restart`: ядро собирает этот файл из шаблона заново. Значит ручная отладка на коробке ставится **после** последнего перезапуска, иначе ожидание обрыва соберёт лог без подробностей.

С включённым уровнем видно всю жизнь клиента: `SAE authentication` → `association OK` → четыре шага `4-Way Handshake` → `AP-STA-CONNECTED`, и отдельной строкой `interface state ENABLED->DISABLED`, когда точку гасят. Этого достаточно, чтобы отличить уход клиента от того, что интерфейс роняет драйвер.

## `timed out to flush queues` не указывает на причину обрыва (2026-09-15)

Сообщение драйвера `rtw89` долго выглядело следом обрывов. Наложение отметок ядра на журнал точки доступа за одну загрузку это опровергает. Часы коробки идут по UTC−5, журнал контейнера — по UTC, поэтому сравнивать нужно после перевода.

| Ядро (коробка) | Что в журнале точки в этот момент |
|---|---|
| 06:08:22 | `AP-STA-DISCONNECTED` — уход клиента |
| 06:11:44 | `AP-STA-DISCONNECTED` — уход клиента |
| 06:46:04 | `AP-STA-DISCONNECTED` — уход клиента |
| 07:20:55 | `AP-STA-DISCONNECTED` — уход клиента |
| 07:23:59 | `interface state ENABLED->DISABLED` — гашение точки (перезапуск) |
| 07:24:48 | `association OK` — **успешное подключение** |
| 08:12:36 | гашение точки (перезапуск) |
| 09:13:55 | `AP-STA-CONNECTED` — **успешное подключение** |

Вывод: сообщение сопровождает **любую** смену состояния станции — потерю, гашение интерфейса и подключение одинаково. Это отметка о сбросе очередей при смене состояния, а не диагноз. Искать по нему причину обрывов бессмысленно.

## Кто разрывает связь: не точка и не клиент кадром управления

За всю загрузку в журнале точки с включённой отладкой: `inactivity` — 0, `low ack` — 0, `ACK` — 0, `disassociated` — 0, `deauthenticated` — 0, `MLME-DISASSOCIATE` — 0. Единственный `MLME-DEAUTHENTICATE` относится к нашему же перезапуску точки.

То есть настоящие обрывы выглядят как голая строка `AP-STA-DISCONNECTED` без единого кадра управления с обеих сторон: точка клиента не выгоняла (нет ни выгона по бездействию, ни по потерянным подтверждениям), клиент не прощался. Станция просто исчезает из виду точки — это потеря на уровне радио и драйвера, а не разрыв по протоколу.

Как отличить свой перезапуск от настоящего обрыва в журнале: у перезапуска первой идёт строка `interface state ENABLED->DISABLED`, затем `AP-DISABLED` и `CTRL-EVENT-TERMINATING`. У настоящего обрыва перед `AP-STA-DISCONNECTED` нет ничего.

Наблюдаемая частота при активном клиенте: разрывы примерно раз в 30–45 минут (11:08, 11:11, 11:46, 12:20 UTC). Самый длинный чистый отрезок — 1 ч 41 мин, но он частично объясняется тем, что телефон 44 минуты вообще отсутствовал на точке.



## Кто на самом деле снимает станцию: опрос по бездействию (2026-09-18)

Прежний вывод («ни одного кадра управления с обеих сторон, станция просто исчезает») сделан по
журналу hostapd. Съёмка событий nl80211 (`iw event -t`) показывает больше, и картина другая.

Обрыв 2026-09-18, 20:08 UTC, после 91 минуты связи:

```
probe client 92:da:e8:fa:f8:63 (cookie ed): no ack
mgmt TX status (cookie ee): no ack
mgmt TX status (cookie ef): no ack
del station 92:da:e8:fa:f8:63
```

Счётчики станции за две секунды до этого: `signal=-71 retries=0 failed=11 inactive=277168ms`.

То есть телефон молчал **277 секунд**, точка опросила его кадром, ответа не получила и сняла
станцию. Порог — `ap_max_inactivity`, по умолчанию **300 секунд**; в примере конфигурации hostapd
это описано прямо: опрос нужен, «чтобы клиент не считал связь оборванной из-за немедленного
disassociate», и станция может подключиться снова, если она в зоне.

`timed out to flush queues` от `rtw89` стоит в ту же секунду — как и в прежних наблюдениях,
сопровождает смену состояния и ничего не объясняет.

**Что изменено:** `engine/hostapd.py` пишет `ap_max_inactivity=1800`. На домашней точке молчащий
клиент — это телефон в кармане, а не ушедшая станция; пять минут для него мало, полчаса разумно.

**Чего это НЕ доказывает:** что сентябрьские обрывы раз в 30–45 минут были тем же самым. Тогда
съёмки радио-уровня не было, а `tx failed` был нулевым при активном клиенте. Теперь механизм
измеряем: в `/var/log/vibedpn-wifi/` лежат события, счётчики и ядро с одними часами, и у каждого
следующего обрыва видно, было перед ним бездействие или нет.

**Метод, который это дал:** `iw event -t` в файл, счётчики станции раз в две секунды в файл,
`journalctl -kf` в файл — три источника с общими часами. Журнала hostapd для вопросов радио-уровня
не хватает, сколько ни повышай его подробность.
