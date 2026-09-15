#!/bin/sh
# The Wi-Fi stand (tests/e2e/wifi.sh) inside a Debian 13 virtual machine.
#
# wifi.sh needs the mac80211_hwsim module. GitHub-hosted runners boot an Azure kernel without it
# (docs/knowledge/ci/e2eStand.md), while the stock Debian kernel ships it. So the runner boots the
# Debian cloud image "generic" (stock kernel, cloud-init) under KVM, installs the box there with the
# repository's own install.sh from this very checkout, builds the images and runs wifi.sh unchanged.
#
# Needs: Linux with /dev/kvm, qemu-system-x86_64, qemu-img, cloud-localds (cloud-image-utils), ssh,
# curl, the internet. VIBEDPN_E2E_VM_IMAGE: a local debian-13-generic-amd64.qcow2 instead of a download.
set -eu

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
IMAGE_URL="https://cloud.debian.org/images/cloud/trixie/latest/debian-13-generic-amd64.qcow2"
VM_USER=e2e
VM_MEMORY_MB=4096
VM_CPUS=2
VM_DISK=20G
SSH_PORT=2222
BOOT_TIMEOUT=300
BRANCH=e2e-vm
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

for tool in qemu-system-x86_64 qemu-img cloud-localds ssh ssh-keygen curl; do
  command -v "$tool" >/dev/null 2>&1 || fail "no $tool (Debian/Ubuntu: qemu-system-x86 qemu-utils cloud-image-utils)"
done
[ -w /dev/kvm ] || fail "/dev/kvm is not writable: the stand needs hardware virtualization"

log "vm: the Debian 13 cloud image with the stock kernel"
image="${VIBEDPN_E2E_VM_IMAGE:-$WORK/debian.qcow2}"
if [ ! -f "$image" ]; then
  curl -fsSL -o "$image" "$IMAGE_URL" || fail "cannot download $IMAGE_URL"
fi
qemu-img create -q -f qcow2 -F qcow2 -b "$image" "$WORK/disk.qcow2" "$VM_DISK"
ssh-keygen -q -t ed25519 -N "" -f "$WORK/key"
cat >"$WORK/user-data" <<EOF
#cloud-config
users:
  - name: $VM_USER
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/sh
    ssh_authorized_keys:
      - $(cat "$WORK/key.pub")
EOF
cloud-localds "$WORK/seed.img" "$WORK/user-data"
qemu-system-x86_64 -enable-kvm -cpu host -m "$VM_MEMORY_MB" -smp "$VM_CPUS" \
  -drive "file=$WORK/disk.qcow2,if=virtio" -drive "file=$WORK/seed.img,if=virtio,format=raw" \
  -netdev "user,id=net0,hostfwd=tcp:127.0.0.1:$SSH_PORT-:22" -device virtio-net-pci,netdev=net0 \
  -display none -serial "file:$WORK/serial.log" -daemonize -pidfile "$WORK/qemu.pid"

i=0
until vm true 2>/dev/null; do
  i=$((i + 5))
  [ "$i" -lt "$BOOT_TIMEOUT" ] || fail "the VM did not answer over ssh in $BOOT_TIMEOUT s"
  sleep 5
done
vm 'uname -r; /usr/sbin/modinfo -n mac80211_hwsim' || fail "the VM kernel has no mac80211_hwsim"

log "vm: this checkout, installed by install.sh as on a box"
tar -C "$REPO" -cf - . | vm "mkdir -p src && tar -C src -xf -"
vm "sudo DEBIAN_FRONTEND=noninteractive apt-get update -q >/dev/null && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q git iw wpasupplicant dhcpcd-base curl >/dev/null" ||
  fail "cannot install git and the device-side tools in the VM"
# install.sh clones the copy as root, and git refuses a repository another user owns
vm "sudo git config --system --add safe.directory '*' && git -C src checkout -q -B $BRANCH" ||
  fail "cannot branch the copied checkout"
vm "sudo VIBEDPN_REPO=\$HOME/src VIBEDPN_BRANCH=$BRANCH bash src/install.sh" || fail "install.sh failed in the VM"

log "vm: the images the box runs"
vm "cd src && sudo docker build -q -t ghcr.io/borodatych/vibedpn-core:e2e core >/dev/null && sudo docker build -q -t ghcr.io/borodatych/vibedpn-dnsmasq:e2e images/dnsmasq >/dev/null && sudo docker build -q -t ghcr.io/borodatych/vibedpn-hostapd:e2e images/hostapd >/dev/null" ||
  fail "cannot build the images in the VM"

log "vm: the Wi-Fi stand"
# a fresh session: install.sh put the user into the docker group
vm "cd src && VIBEDPN_TAG=e2e VIBEDPN_E2E_PYTHON=/opt/vibedpn/venv/bin/python sh tests/e2e/wifi.sh" ||
  fail "the Wi-Fi stand failed in the VM"
log "E2E-WIFI-VM-OK"
