#!/bin/bash -e
# pi-gen: on the build host, copy what provision.sh needs into the root filesystem of the image.
# files/ is filled by images/os/pi-gen/build.sh from images/os/common and install.sh.
# NN-run-chroot.sh reaches the chroot through stdin (on_chroot < file), where the variables of
# the build do not exist: the revision of VibeDPN goes in as a file instead.
install -d "${ROOTFS_DIR}/var/tmp/vibedpn-image"
cp files/* "${ROOTFS_DIR}/var/tmp/vibedpn-image/"
{
  printf 'VIBEDPN_REPO=%s\n' "${VIBEDPN_REPO:?set by images/os/pi-gen/build.sh in config}"
  printf 'VIBEDPN_BRANCH=%s\n' "${VIBEDPN_BRANCH:?set by images/os/pi-gen/build.sh in config}"
} >"${ROOTFS_DIR}/var/tmp/vibedpn-image/env"
