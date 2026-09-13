#!/bin/sh
# Build the VibeDPN image for Raspberry Pi (arm64) with pi-gen in Docker.
#   VIBEDPN_BRANCH=next sh images/os/pi-gen/build.sh
# Needs: an arm64 Linux host (or binfmt + qemu-user-static), Docker, git, tens of GB of disk.
# The result: images/os/pi-gen/work/deploy/*.img.xz
set -eu

REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
HERE="$REPO/images/os/pi-gen"
WORK="$HERE/work"
# pi-gen, branch arm64, pinned (git ls-remote https://github.com/RPi-Distro/pi-gen, 2026-09-13)
PI_GEN_REPO="https://github.com/RPi-Distro/pi-gen.git"
PI_GEN_COMMIT="86919dae864359499d8148a49910a558d49a00f1"
export VIBEDPN_REPO="${VIBEDPN_REPO:-https://github.com/borodatych/VibeDPN.git}"
export VIBEDPN_BRANCH="${VIBEDPN_BRANCH:-main}"

if [ ! -d "$WORK/.git" ]; then
  git clone -q "$PI_GEN_REPO" "$WORK"
fi
git -C "$WORK" fetch -q origin "$PI_GEN_COMMIT"
git -C "$WORK" checkout -q "$PI_GEN_COMMIT"

rm -rf "$WORK/stage-vibedpn"
cp -R "$HERE/stage-vibedpn" "$WORK/stage-vibedpn"
files="$WORK/stage-vibedpn/00-vibedpn/files"
mkdir -p "$files"
cp "$REPO/install.sh" "$REPO/images/os/common/provision.sh" "$REPO/images/os/common/firstLogin.sh" "$files/"
cp "$HERE/config" "$WORK/config"
# pi-gen sources config without exporting it, and runs NN-run.sh as a child process: export here
{
  echo "export VIBEDPN_REPO=\"$VIBEDPN_REPO\""
  echo "export VIBEDPN_BRANCH=\"$VIBEDPN_BRANCH\""
} >>"$WORK/config"

cd "$WORK"
./build-docker.sh
