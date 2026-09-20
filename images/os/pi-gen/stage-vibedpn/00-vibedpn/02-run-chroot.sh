#!/bin/bash -e
# pi-gen: inside the image — Docker, the checkout and the CLI, the first-login wizard.
# The revision of VibeDPN comes from the file 01-run.sh wrote (variables of the build stay outside).
set -a
# shellcheck source=/dev/null  # written by 01-run.sh inside the image during the build
. /var/tmp/vibedpn-image/env
set +a
sh /var/tmp/vibedpn-image/provision.sh
