# shellcheck shell=sh
# VibeDPN OS image: opens the setup wizard at the first interactive login, until the box is set up.
# Installed as /etc/profile.d/vibedpn-first-login.sh (sourced by login shells, so POSIX sh only).
# The image carries no role and no password (docs/decisions.md, decision 15): only the owner can
# answer `vibedpn init`, so it is offered at the first console or SSH login instead of on boot.
if [ -t 0 ] && [ -t 1 ] && [ ! -e /opt/vibedpn/config.yaml ] && command -v vibedpn >/dev/null 2>&1; then
  printf '\nVibeDPN is installed but not set up yet. Starting: sudo vibedpn init\n'
  printf 'Leave it with Ctrl+C; it starts again at the next login until config.yaml exists.\n\n'
  sudo vibedpn init && printf '\nNext step: sudo vibedpn up\n\n'
fi
