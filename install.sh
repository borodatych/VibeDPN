#!/usr/bin/env bash
# VibeDPN installer for Debian 12/13 and Raspberry Pi OS 64-bit (amd64, arm64).
#
#   curl -fsSL https://raw.githubusercontent.com/borodatych/VibeDPN/main/install.sh | sudo bash
#
# What it does, idempotently (re-running updates the checkout and the CLI):
#   1. installs Docker Engine + Compose plugin from download.docker.com (skipped if present),
#   2. clones the repository into /opt/vibedpn (or fast-forwards an existing clone),
#   3. builds the `vibedpn` CLI into /opt/vibedpn/venv on the system Python and links it to
#      /usr/local/bin/vibedpn,
#   4. adds the invoking user to the `docker` group.
# Overrides: VIBEDPN_REPO (git URL or path), VIBEDPN_BRANCH (default main), VIBEDPN_DIR.
set -euo pipefail

VIBEDPN_REPO="${VIBEDPN_REPO:-https://github.com/borodatych/VibeDPN.git}"
VIBEDPN_BRANCH="${VIBEDPN_BRANCH:-main}"
DEFAULT_DIR="/opt/vibedpn"  # `vibedpn init` has the same default; keep them equal
VIBEDPN_DIR="${VIBEDPN_DIR:-$DEFAULT_DIR}"
VIBEDPN_BIN="/usr/local/bin/vibedpn"
MIN_PYTHON="3.11"
DOCKER_KEYRING="/etc/apt/keyrings/docker.asc"
DOCKER_SOURCES="/etc/apt/sources.list.d/docker.sources"
DOCKER_PACKAGES="docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin"

log() { printf '\033[1;34m[vibedpn]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[vibedpn] error:\033[0m %s\n' "$*" >&2; exit 1; }

require_root() {
  [ "$(id -u)" -eq 0 ] || die "run as root: sudo bash install.sh"
}

# Sets CODENAME and ARCH; refuses anything but Debian bookworm/trixie on amd64/arm64.
detect_platform() {
  [ -r /etc/os-release ] || die "cannot read /etc/os-release"
  # shellcheck disable=SC1091
  . /etc/os-release
  [ "${ID:-}" = "debian" ] \
    || die "unsupported OS '${ID:-unknown}': VibeDPN needs Debian 12/13 or Raspberry Pi OS 64-bit"
  case "${VERSION_CODENAME:-}" in
    bookworm | trixie) CODENAME="$VERSION_CODENAME" ;;
    *) die "unsupported Debian release '${VERSION_CODENAME:-unknown}' (need bookworm or trixie)" ;;
  esac
  ARCH="$(dpkg --print-architecture)"
  case "$ARCH" in
    amd64 | arm64) ;;
    *) die "unsupported architecture '$ARCH' (need amd64 or arm64; 32-bit Raspberry Pi OS is not supported)" ;;
  esac
  log "Debian ${VERSION_ID:-?} ($CODENAME), $ARCH"
}

install_base_packages() {
  log "Installing base packages"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends ca-certificates curl git iproute2 python3 python3-venv >/dev/null
}

# Official apt repository of Docker (https://docs.docker.com/engine/install/debian/); Raspberry Pi
# OS 64-bit follows the same instructions per https://docs.docker.com/engine/install/raspberry-pi-os/.
install_docker() {
  if docker compose version >/dev/null 2>&1; then
    log "Docker Compose already present: $(docker compose version --short)"
    return
  fi
  log "Installing Docker Engine from download.docker.com"
  install -m 0755 -d "$(dirname "$DOCKER_KEYRING")"
  curl -fsSL https://download.docker.com/linux/debian/gpg -o "$DOCKER_KEYRING"
  chmod a+r "$DOCKER_KEYRING"
  cat >"$DOCKER_SOURCES" <<SOURCES
Types: deb
URIs: https://download.docker.com/linux/debian
Suites: $CODENAME
Components: stable
Architectures: $ARCH
Signed-By: $DOCKER_KEYRING
SOURCES
  apt-get update -qq
  # shellcheck disable=SC2086  # package list is intentionally word-split
  apt-get install -y -qq $DOCKER_PACKAGES >/dev/null
  log "Docker: $(docker --version), $(docker compose version --short)"
}

clone_or_update() {
  if [ -d "$VIBEDPN_DIR/.git" ]; then
    log "Updating $VIBEDPN_DIR to $VIBEDPN_BRANCH"
    git -C "$VIBEDPN_DIR" fetch -q origin "$VIBEDPN_BRANCH"
    git -C "$VIBEDPN_DIR" checkout -q "$VIBEDPN_BRANCH"
    git -C "$VIBEDPN_DIR" merge -q --ff-only "origin/$VIBEDPN_BRANCH"
  else
    log "Cloning $VIBEDPN_REPO ($VIBEDPN_BRANCH) into $VIBEDPN_DIR"
    git clone -q --branch "$VIBEDPN_BRANCH" "$VIBEDPN_REPO" "$VIBEDPN_DIR"
  fi
}

python_version_of() {
  "$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])'
}

version_at_least() {
  [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]
}

# System Python only: no third-party installers on the box. Dependencies are pinned with hashes
# (core/requirements.txt, exported from uv.lock); the package itself is built without isolation.
install_cli() {
  local venv="$VIBEDPN_DIR/venv" system_python venv_python
  system_python="$(python_version_of python3)"
  version_at_least "$system_python" "$MIN_PYTHON" \
    || die "python3 $system_python is too old (need >= $MIN_PYTHON)"
  venv_python=""
  [ -x "$venv/bin/python" ] && venv_python="$(python_version_of "$venv/bin/python")"
  if [ "$venv_python" != "$system_python" ]; then
    log "Creating venv with Python $system_python"
    rm -rf "$venv"
    python3 -m venv "$venv"
  fi
  log "Installing the vibedpn CLI"
  "$venv/bin/pip" install -q --require-hashes -r "$VIBEDPN_DIR/core/requirements.txt"
  "$venv/bin/pip" install -q --no-deps --no-build-isolation "$VIBEDPN_DIR/core"
  ln -sfn "$venv/bin/vibedpn" "$VIBEDPN_BIN"
  log "CLI: $("$VIBEDPN_BIN" --version)"
}

add_docker_group() {
  local user="${SUDO_USER:-}"
  { [ -n "$user" ] && [ "$user" != "root" ]; } || return 0
  getent group docker >/dev/null || return 0
  if ! id -nG "$user" | tr ' ' '\n' | grep -qx docker; then
    usermod -aG docker "$user"
    log "Added $user to group docker (log out and in again for it to apply)"
  fi
}

main() {
  require_root
  detect_platform
  install_base_packages
  install_docker
  clone_or_update
  install_cli
  add_docker_group
  if [ "$VIBEDPN_DIR" = "$DEFAULT_DIR" ]; then
    log "Done. Next step: sudo vibedpn init"
  else
    log "Done. Next step: sudo vibedpn init --dir \"$VIBEDPN_DIR\""
  fi
}

main "$@"
