#!/usr/bin/env bash
# Pulls a fresh backup OFF the box onto the owner's machine and keeps the newest few. Runs on the
# OWNER'S machine, never on the box: the box gets no key and no path of its own to this machine,
# so whoever takes the box takes no backups with it.
#
# The archive holds secrets in the clear (config.yaml, .env, secrets/). It is written 600 here and
# the directory is created 700; keep it where you keep passwords.
#
# `vibedpn backup` stops the services of the box for the copy — the household loses the network
# for those seconds. Schedule it at night, not at dinner.
#
# Idempotent: a second run in the same minute pulls a second archive and prunes the oldest.
set -euo pipefail

readonly DEFAULT_ALIAS=vibedpn
readonly DEFAULT_DIR="$HOME/vibedpn-backups"
readonly DEFAULT_KEEP=14

sshAlias="${VIBEDPN_SSH_ALIAS:-$DEFAULT_ALIAS}"
# An ssh configuration of its own, when the caller has one. A background job on macOS cannot read
# a personal ~/.ssh/config that includes a file on an external volume: ssh refuses to start at all
# ("Operation not permitted", knowledge platform/launchdExternalVolume.md), so the timer hands the
# job a small config with just this box in it.
sshConfig="${VIBEDPN_SSH_CONFIG:-}"
backupDir="${VIBEDPN_BACKUP_DIR:-$DEFAULT_DIR}"
keep="${VIBEDPN_BACKUP_KEEP:-$DEFAULT_KEEP}"

sshTo() {
  if [ -n "$sshConfig" ]; then
    ssh -F "$sshConfig" -o BatchMode=yes "$@"
  else
    ssh -o BatchMode=yes "$@"
  fi
}

log() { printf '\033[1;34m[vibedpn]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[vibedpn] error:\033[0m %s\n' "$*" >&2; exit 1; }

[[ "$keep" =~ ^[0-9]+$ ]] && [ "$keep" -ge 1 ] || die "VIBEDPN_BACKUP_KEEP must be a number >= 1"

# The box answers with `wrote <path> (...)`; the path is what has to be fetched. A silent or
# differently shaped answer stops the run: pulling the wrong file would look like a backup.
log "Asking $sshAlias for a fresh backup (its services pause for the copy)"
answer="$(sshTo "$sshAlias" 'sudo -n vibedpn backup')" \
  || die "backup on $sshAlias failed; run it by hand: ssh $sshAlias 'sudo vibedpn backup'"
remote="$(printf '%s\n' "$answer" | sed -n 's/^wrote \([^ ]*\) .*/\1/p' | tail -1)"
[ -n "$remote" ] || die "cannot tell the archive from the answer: $answer"

mkdir -p "$backupDir"
chmod 700 "$backupDir"
name="$(basename "$remote")"
log "Fetching $name"
# scp of a root-owned file needs the same sudo as the backup itself, so it is streamed instead.
sshTo "$sshAlias" "sudo -n cat '$remote'" > "$backupDir/$name.part"
mv "$backupDir/$name.part" "$backupDir/$name"
chmod 600 "$backupDir/$name"
[ -s "$backupDir/$name" ] || die "the archive arrived empty: $backupDir/$name"
tar -tzf "$backupDir/$name" >/dev/null || die "the archive is not readable: $backupDir/$name"
log "Kept $backupDir/$name ($(du -h "$backupDir/$name" | cut -f1))"

# Both sides are pruned: the box has one disk for everything it does, and a daily archive of
# data/ fills it quietly. No mapfile and no `xargs -r` here — the owner's machine may be a Mac,
# where bash is 3.2 and has neither; the names are ours and hold no newlines.
# Sorted by age, which find cannot do portably.
# shellcheck disable=SC2012
ls -1t "$backupDir"/vibedpn-*.tar.gz 2>/dev/null | tail -n +$((keep + 1)) | while IFS= read -r old; do
  log "Pruning $(basename "$old")"
  rm -f -- "$old"
done

sshTo "$sshAlias" \
  "sudo -n sh -c 'ls -1t /opt/vibedpn/backups/vibedpn-*.tar.gz 2>/dev/null | tail -n +$((keep + 1)) | while read -r old; do rm -f \"\$old\"; done'" \
  || log "could not prune the archives on the box; do it there by hand"

held="$(find "$backupDir" -maxdepth 1 -name 'vibedpn-*.tar.gz' | wc -l | tr -d ' ')"
log "Done. $held archive(s) in $backupDir"
