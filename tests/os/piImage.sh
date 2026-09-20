#!/bin/sh
# Checks a built Raspberry Pi image of VibeDPN (images/os/pi-gen) without a Raspberry Pi: mounts the
# image and looks at what the owner gets — the checkout, the CLI, Docker, the first-login wizard,
# the cloud-init seed on the boot partition, a locked user and no secret — and runs the installed
# CLI and Docker in a chroot of the root filesystem.
#   sudo tests/os/piImage.sh images/os/pi-gen/work/deploy/image_2026-09-20-vibedpn-arm64.img.xz
# Needs root (losetup, mount, chroot) and, on a host that is not arm64, the binfmt registration of
# qemu-aarch64 (Debian: qemu-user-binfmt). A real boot on the hardware is not what this checks.
set -eu

IMAGE="${1:?the image to check, .img or .img.xz}"
WORK="$(mktemp -d "${TMPDIR:-/var/tmp}/vibedpn-pi-image.XXXXXX")"
LOOP=""

log() {
  echo "== $*"
}

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

cleanup() {
  umount "$WORK/root/proc" 2>/dev/null || true
  umount "$WORK/root/dev" 2>/dev/null || true
  umount "$WORK/root/boot/firmware" 2>/dev/null || true
  umount "$WORK/root" 2>/dev/null || true
  [ -z "$LOOP" ] || losetup -d "$LOOP" 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT INT TERM

[ "$(id -u)" = 0 ] || fail "run as root: losetup, mount and chroot"
for tool in losetup mount chroot xz; do
  command -v "$tool" >/dev/null 2>&1 || fail "no $tool"
done
[ -f "$IMAGE" ] || fail "no image $IMAGE"
if [ "$(uname -m)" != aarch64 ]; then
  ls /proc/sys/fs/binfmt_misc/qemu-aarch64* >/dev/null 2>&1 ||
    fail "the host is not arm64 and has no binfmt for qemu-aarch64 (Debian: qemu-user-binfmt)"
fi

log "the image, unpacked"
case "$IMAGE" in
  *.xz) xz -dc "$IMAGE" >"$WORK/disk.img" ;;
  *) cp --sparse=always "$IMAGE" "$WORK/disk.img" ;;
esac
LOOP="$(losetup -fP --show "$WORK/disk.img")"
[ -b "${LOOP}p1" ] && [ -b "${LOOP}p2" ] || fail "the image has no two partitions (boot and root)"
mkdir -p "$WORK/root"
mount -o ro "${LOOP}p2" "$WORK/root"
mount -o ro "${LOOP}p1" "$WORK/root/boot/firmware"
ROOT="$WORK/root"

log "what the owner gets"
[ -d "$ROOT/opt/vibedpn/.git" ] || fail "no checkout in /opt/vibedpn"
# the CLI is a symlink with an absolute target: -x on it would ask the HOST for /opt/vibedpn
# (on a box that runs VibeDPN the check then passes for the wrong reason). Resolve inside the image.
[ -L "$ROOT/usr/local/bin/vibedpn" ] || fail "no CLI symlink /usr/local/bin/vibedpn"
cli_target="$(readlink "$ROOT/usr/local/bin/vibedpn")"
case "$cli_target" in
  /*) [ -x "$ROOT$cli_target" ] || fail "the CLI symlink points at $cli_target, which the image does not have" ;;
  *) fail "the CLI symlink is relative ($cli_target): install.sh writes an absolute one" ;;
esac
[ -f "$ROOT/etc/profile.d/vibedpn-first-login.sh" ] || fail "no first-login script"
[ ! -e "$ROOT/opt/vibedpn/config.yaml" ] || fail "the image carries a config.yaml"
grep -qx vibedpn "$ROOT/etc/hostname" || fail "hostname is not vibedpn"
for pkg in docker-ce docker-compose-plugin cloud-init; do
  awk -v p="$pkg" '$1=="Package:" {pkg=$2} $1=="Status:" && pkg==p && $0 ~ /install ok installed/ {found=1} END {exit !found}' \
    "$ROOT/var/lib/dpkg/status" || fail "package $pkg is not installed in the image"
done
for unit in docker.service ssh.service; do
  [ -L "$ROOT/etc/systemd/system/multi-user.target.wants/$unit" ] || fail "$unit is not enabled in the image"
done
for f in meta-data user-data network-config; do
  [ -f "$ROOT/boot/firmware/$f" ] || fail "no $f on the boot partition (the cloud-init seed Raspberry Pi Imager overwrites)"
done

log "no secret inside"
grep -q '^vibedpn:' "$ROOT/etc/passwd" || fail "no user vibedpn"
grep -q '^vibedpn:[!*]' "$ROOT/etc/shadow" || fail "the user vibedpn has a password"
[ ! -s "$ROOT/home/vibedpn/.ssh/authorized_keys" ] || fail "the image carries an authorized_keys"
[ ! -e "$ROOT/opt/vibedpn/secrets" ] || fail "the image carries secrets/"
if ls "$ROOT"/etc/ssh/ssh_host_*_key >/dev/null 2>&1; then
  fail "the image carries SSH host keys: every box would share them"
fi

log "the installed software runs (chroot)"
mount -t proc proc "$ROOT/proc"
mount --bind /dev "$ROOT/dev"
chroot "$ROOT" /usr/local/bin/vibedpn --version || fail "vibedpn --version failed in the chroot"
chroot "$ROOT" docker --version || fail "docker --version failed in the chroot"
chroot "$ROOT" git -C /opt/vibedpn log -1 --format='%h %s' || fail "the checkout has no history"
if [ -n "${VIBEDPN_OS_BRANCH:-}" ]; then
  branch="$(chroot "$ROOT" git -C /opt/vibedpn rev-parse --abbrev-ref HEAD)"
  [ "$branch" = "$VIBEDPN_OS_BRANCH" ] || fail "the checkout is on $branch, expected $VIBEDPN_OS_BRANCH"
fi
log "PI-IMAGE-OK"
