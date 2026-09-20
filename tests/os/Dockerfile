# The tools of tests/os/uefiBoot.sh in a throwaway container, for a box without them on the host:
#   docker build -t vibedpn-qemu-test tests/os
#   docker run --rm --device /dev/kvm -v "$PWD:/repo" -w /repo vibedpn-qemu-test sh tests/os/uefiBoot.sh vibedpn-amd64.img
FROM debian:trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      qemu-system-x86 qemu-system-arm ovmf qemu-efi-aarch64 mtools openssh-client ca-certificates \
    && rm -rf /var/lib/apt/lists/*
