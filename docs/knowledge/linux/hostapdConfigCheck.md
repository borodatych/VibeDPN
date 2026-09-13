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
