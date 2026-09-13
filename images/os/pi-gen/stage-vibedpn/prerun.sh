#!/bin/bash -e
# pi-gen stage prerun: start from the root filesystem of the previous stage.
if [ ! -d "${ROOTFS_DIR}" ]; then
  copy_previous
fi
