#!/bin/sh
# Boots a UEFI image of VibeDPN (images/os/debos) in QEMU and checks what the owner meets on the
# first boot: cloud-init makes the user from user-data on the CIDATA partition, SSH answers with the
# key from it, Docker and the CLI are in place, and the first login opens `vibedpn init`.
#   tests/os/uefiBoot.sh vibedpn-amd64.img
# The architecture comes from the file name (amd64 or arm64); the native one runs under KVM, the
# other is emulated and slow. The image file is not touched: the test boots a copy.
# Needs: qemu-system-x86_64 with OVMF (Debian/Ubuntu: qemu-system-x86 ovmf) or qemu-system-aarch64
# with AAVMF (qemu-system-arm qemu-efi-aarch64), mtools, ssh, ssh-keygen.
set -eu

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
IMAGE="${1:?the image to boot, e.g. vibedpn-amd64.img}"
VM_USER=vibedpn
VM_MEMORY_MB=2048
VM_CPUS=2
SSH_PORT="${VIBEDPN_OS_SSH_PORT:-2223}"
# the CIDATA partition starts at 1 MiB (images/os/debos/vibedpn.yaml); mlabel checks the label
CIDATA_OFFSET=1048576
WORK="$(mktemp -d)"

log() {
  echo "== $*"
}

fail() {
  echo "FAIL: $*" >&2
  if [ -f "$WORK/serial.log" ]; then
    echo "# serial console (tail)" >&2
    tail -n 40 "$WORK/serial.log" >&2
  fi
  exit 1
}

cleanup() {
  if [ -f "$WORK/qemu.pid" ]; then
    kill "$(cat "$WORK/qemu.pid")" 2>/dev/null || true
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT INT TERM

vm() {
  ssh -i "$WORK/key" -p "$SSH_PORT" -o BatchMode=yes -o ConnectTimeout=5 \
    -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
    "$VM_USER@127.0.0.1" "$@"
}

[ -f "$IMAGE" ] || fail "no image $IMAGE"
case "$IMAGE" in
  *amd64*)
    ARCH=amd64
    QEMU=qemu-system-x86_64
    MACHINE=q35
    FW_CODE="${VIBEDPN_OS_FW_CODE:-/usr/share/OVMF/OVMF_CODE_4M.fd}"
    FW_VARS="${VIBEDPN_OS_FW_VARS:-/usr/share/OVMF/OVMF_VARS_4M.fd}"
    native=x86_64
    ;;
  *arm64*)
    ARCH=arm64
    QEMU=qemu-system-aarch64
    MACHINE=virt
    FW_CODE="${VIBEDPN_OS_FW_CODE:-/usr/share/AAVMF/AAVMF_CODE.fd}"
    FW_VARS="${VIBEDPN_OS_FW_VARS:-/usr/share/AAVMF/AAVMF_VARS.fd}"
    native=aarch64
    ;;
  *) fail "cannot tell the architecture from the name $IMAGE (expected amd64 or arm64 in it)" ;;
esac
for tool in "$QEMU" mcopy mlabel mdir ssh ssh-keygen; do
  command -v "$tool" >/dev/null 2>&1 || fail "no $tool (Debian/Ubuntu: qemu-system-x86 ovmf, qemu-system-arm qemu-efi-aarch64, mtools)"
done
[ -f "$FW_CODE" ] && [ -f "$FW_VARS" ] || fail "no UEFI firmware $FW_CODE / $FW_VARS (Debian/Ubuntu: ovmf or qemu-efi-aarch64)"
if [ "$(uname -m)" = "$native" ] && [ -w /dev/kvm ]; then
  ACCEL=kvm
  CPU=host
  BOOT_TIMEOUT=300
else
  ACCEL=tcg
  CPU=max
  BOOT_TIMEOUT=1800
  log "$ARCH is not the host architecture with KVM: emulating, this is slow"
fi

log "$ARCH: a copy of $IMAGE with the owner's user-data on the CIDATA partition"
cp --sparse=always "$IMAGE" "$WORK/disk.img"
# the owner writes the image on a bigger disk: the first boot must grow the root partition and filesystem
truncate -s +2G "$WORK/disk.img"
cp "$FW_VARS" "$WORK/vars.fd"
ssh-keygen -q -t ed25519 -N "" -f "$WORK/key"
# the owner's path (docs/manuals/osImages.md): user-data.example with their key in it
sed "/replace-with-your-key/s|.*|      - $(cat "$WORK/key.pub")|" \
  "$REPO/images/os/common/seed/user-data.example" >"$WORK/user-data"
grep -q "ssh-ed25519 AAAA" "$WORK/user-data" || fail "the key did not land in user-data: the placeholder in user-data.example changed?"
export MTOOLS_SKIP_CHECK=1
mlabel -s -i "$WORK/disk.img@@$CIDATA_OFFSET" :: | grep -q CIDATA || fail "the first partition is not labelled CIDATA"
mdir -b -i "$WORK/disk.img@@$CIDATA_OFFSET" :: | grep -q "meta-data" || fail "no meta-data on the CIDATA partition"
mcopy -o -i "$WORK/disk.img@@$CIDATA_OFFSET" "$WORK/user-data" ::user-data || fail "cannot write user-data to the CIDATA partition"

log "$ARCH: boot under $ACCEL"
"$QEMU" -machine "$MACHINE" -accel "$ACCEL" -cpu "$CPU" -m "$VM_MEMORY_MB" -smp "$VM_CPUS" \
  -drive "if=pflash,format=raw,readonly=on,file=$FW_CODE" -drive "if=pflash,format=raw,file=$WORK/vars.fd" \
  -drive "file=$WORK/disk.img,format=raw,if=virtio" \
  -netdev "user,id=net0,hostfwd=tcp:127.0.0.1:$SSH_PORT-:22" -device virtio-net-pci,netdev=net0 \
  -display none -serial "file:$WORK/serial.log" -daemonize -pidfile "$WORK/qemu.pid"
i=0
until vm true 2>/dev/null; do
  i=$((i + 5))
  [ "$i" -lt "$BOOT_TIMEOUT" ] || fail "the image did not answer over ssh in $BOOT_TIMEOUT s"
  sleep 5
done
log "ssh answered after about $i s"

log "$ARCH: what is inside"
vm "hostname" | grep -qx vibedpn || fail "hostname is not vibedpn (cloud-init did not apply user-data?)"
vm "sudo -n true" || fail "the user has no passwordless sudo"
vm "sudo -n grep -q '^vibedpn:[!*]' /etc/shadow" || fail "the user vibedpn has a password in the image"
vm "test -x /usr/local/bin/vibedpn && test -d /opt/vibedpn/.git" || fail "no VibeDPN CLI or checkout in the image"
vm "test ! -e /opt/vibedpn/config.yaml" || fail "the image carries a config.yaml"
vm "test -f /etc/profile.d/vibedpn-first-login.sh" || fail "no first-login script in the image"
vm "vibedpn --version" || fail "vibedpn --version failed"
# root owns /opt/vibedpn (install.sh), and git refuses another user's repository
vm "sudo -n git -C /opt/vibedpn log -1 --format='%h %s'" || fail "the checkout in /opt/vibedpn has no history"
vm "systemctl is-active docker >/dev/null && sudo -n docker info --format 'docker {{.ServerVersion}}'" || fail "Docker is not running in the image"
vm "cloud-init status --wait >/dev/null" || fail "cloud-init did not finish cleanly: $(vm 'cloud-init status --long' 2>&1)"
root_bytes="$(vm "df --output=size -B1 / | tail -1")"
[ "${root_bytes:-0}" -gt 6500000000 ] || fail "the root filesystem did not grow to the disk (${root_bytes:-?} bytes): growpart or resizefs failed"
# the recipe removes the host keys openssh-server made at build; cloud-init makes new ones on boot
vm "sudo -n find /etc/ssh -name 'ssh_host_*_key' -newer /usr/local/bin/vibedpn | grep -q ." ||
  fail "the SSH host keys are older than the build: the image ships them"

log "$ARCH: the first interactive login opens the wizard"
# a login shell on a pty runs /etc/profile.d; Ctrl+C leaves the wizard, then the shell exits
{ sleep 8; printf '\003'; sleep 2; printf 'exit\n'; } |
  timeout 60 ssh -tt -i "$WORK/key" -p "$SSH_PORT" -o BatchMode=yes -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR "$VM_USER@127.0.0.1" >"$WORK/login.log" 2>&1 || true
grep -q "VibeDPN is installed but not set up yet" "$WORK/login.log" || {
  cat "$WORK/login.log" >&2
  fail "the first login did not announce the wizard"
}
grep -q "Role" "$WORK/login.log" || {
  cat "$WORK/login.log" >&2
  fail "vibedpn init did not reach its first question"
}
log "$ARCH: vibedpn init and doctor on the image"
# a single-NIC VM is a vps; the endpoint is a documentation address, nothing is started
vm "printf 'vibedpn-test-password-1\n' >/tmp/pw && sudo -n vibedpn init --role vps --endpoint 203.0.113.10 --password-file /tmp/pw" ||
  fail "vibedpn init failed in the image"
vm "sudo -n vibedpn doctor" >"$WORK/doctor.log" 2>&1 || true
if ! grep -q -E "[0-9]+ ok, [0-9]+ warn, [0-9]+ fail" "$WORK/doctor.log" || grep -q Traceback "$WORK/doctor.log"; then
  cat "$WORK/doctor.log" >&2
  fail "vibedpn doctor did not run through in the image"
fi
# the verdicts: without `vibedpn up` the containers are down, and that is what the fails should be about
grep -E "\[ *(warn|fail) *\]|[0-9]+ ok, [0-9]+ warn, [0-9]+ fail" "$WORK/doctor.log"
log "UEFI-BOOT-OK $ARCH"
