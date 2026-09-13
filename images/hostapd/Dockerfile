# syntax=docker/dockerfile:1
# vibedpn/hostapd: the Wi-Fi access point of gateway mode. core renders hostapd.conf (with the
# passphrase from secrets/wifi-passphrase, mode 600) into ./data/hostapd before the container
# starts (compose: depends_on core healthy).
FROM alpine:3.24
RUN apk add --no-cache hostapd
ENTRYPOINT ["hostapd", "/var/lib/vibedpn-hostapd/hostapd.conf"]
