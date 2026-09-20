#!/bin/sh
# VibeDPN OS image: runs inside the root filesystem of the image (debos `run: chroot`, pi-gen
# `00-run-chroot.sh`). Installs what `install.sh` installs on a live box — Docker Engine, the
# checkout in /opt/vibedpn, the CLI — in its image mode, then the first-login wizard.
# Nothing secret is written: no password, no key, no role (docs/decisions.md, decision 15).
#
# Needs in the environment: VIBEDPN_REPO and VIBEDPN_BRANCH (the revision the image is built from),
# and /var/tmp/vibedpn-image/{install.sh,firstLogin.sh} copied in by the build. Not /tmp: debos runs
# chroot commands through systemd-nspawn, which hides /tmp of the root filesystem under a tmpfs.
set -eu

SOURCE=/var/tmp/vibedpn-image
: "${VIBEDPN_REPO:?the git URL of VibeDPN}"
: "${VIBEDPN_BRANCH:?the branch the image follows}"

VIBEDPN_IMAGE_BUILD=1 VIBEDPN_REPO="$VIBEDPN_REPO" VIBEDPN_BRANCH="$VIBEDPN_BRANCH" \
  bash "$SOURCE/install.sh"

install -m 0644 "$SOURCE/firstLogin.sh" /etc/profile.d/vibedpn-first-login.sh
# the box starts Docker on boot; `vibedpn up` after `init` pulls the images of its branch
systemctl enable docker.service containerd.service

rm -rf "$SOURCE"
apt-get clean
rm -rf /var/lib/apt/lists/*
