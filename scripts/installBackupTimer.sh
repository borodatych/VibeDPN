#!/usr/bin/env bash
# Installs the weekly backup job on the OWNER'S Mac: every Sunday at night it asks the box for a
# fresh archive and keeps the newest few. Runs here, never on the box — the box gets no key and no
# path of its own to this machine.
#
# Why the job does not simply run the script from the repository: macOS keeps background jobs off
# external volumes. A LaunchAgent may neither read, write nor execute anything under /Volumes
# unless the binary it runs is granted Full Disk Access by hand, and it fails with a bare
# "Operation not permitted" (measured 2026-09-20; knowledge platform/launchdExternalVolume.md).
# So the job lives entirely in the home directory: a copy of the script next to its own files, and
# the archives beside it. Re-run this installer after updating the repository to refresh the copy.
#
# Idempotent: it rewrites the copy and the job description and loads the job again.
set -euo pipefail

readonly DEFAULT_DIR="$HOME/VibeDPN-backups"
readonly LABEL=com.vibedpn.backup
readonly SUPPORT="$HOME/Library/Application Support/vibedpn"
readonly PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
readonly LOG="$HOME/Library/Logs/vibedpn-backup.log"
readonly DEFAULT_WEEKDAY=0  # Sunday; 0 and 7 both mean it to launchd
readonly DEFAULT_HOUR=4
readonly DEFAULT_MINUTE=30

backupDir="${VIBEDPN_BACKUP_DIR:-$DEFAULT_DIR}"
keep="${VIBEDPN_BACKUP_KEEP:-14}"
weekday="${VIBEDPN_BACKUP_WEEKDAY:-$DEFAULT_WEEKDAY}"
hour="${VIBEDPN_BACKUP_HOUR:-$DEFAULT_HOUR}"
minute="${VIBEDPN_BACKUP_MINUTE:-$DEFAULT_MINUTE}"
sshAlias="${VIBEDPN_SSH_ALIAS:-vibedpn}"

log() { printf '\033[1;34m[vibedpn]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[vibedpn] error:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = Darwin ] || die "this installer is for macOS; on Linux use a systemd timer or cron"

source="$(cd "$(dirname "$0")" && pwd)/pullBackup.sh"
[ -r "$source" ] || die "cannot read $source"

mkdir -p "$SUPPORT" "$backupDir" "$(dirname "$PLIST")" "$(dirname "$LOG")"
install -m 700 "$source" "$SUPPORT/pullBackup.sh"

# The job gets an ssh configuration of its own: the personal ~/.ssh/config of this machine may
# include files from an external volume (colima writes one), and a background job cannot read
# those at all — ssh then refuses to start, and the backup fails before it begins.
sshConfig="$SUPPORT/ssh_config"
awk -v alias="$sshAlias" '
  $1 == "Host" { inside = ($2 == alias) }
  inside { print }
' "$HOME/.ssh/config" >"$sshConfig" 2>/dev/null || true
[ -s "$sshConfig" ] || die "no 'Host $sshAlias' block in ~/.ssh/config; run scripts/seedKey.sh first"
chmod 600 "$sshConfig"
chmod 700 "$backupDir"

cat >"$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>

  <!-- Written by scripts/installBackupTimer.sh of VibeDPN; re-run it instead of editing this. -->
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>-lc</string>
    <string>VIBEDPN_BACKUP_DIR='$backupDir' VIBEDPN_BACKUP_KEEP='$keep' VIBEDPN_SSH_ALIAS='$sshAlias' VIBEDPN_SSH_CONFIG='$sshConfig' '$SUPPORT/pullBackup.sh'</string>
  </array>

  <!-- At night: the box stops its services for the copy and the household loses the network for
       those seconds (about forty, measured). A job whose time passed while the Mac slept runs
       once after it wakes. -->
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key><integer>$weekday</integer>
    <key>Hour</key><integer>$hour</integer>
    <key>Minute</key><integer>$minute</integer>
  </dict>

  <key>StandardOutPath</key>
  <string>$LOG</string>
  <key>StandardErrorPath</key>
  <string>$LOG</string>
  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
PLIST

plutil -lint "$PLIST" >/dev/null || die "the job description came out invalid: $PLIST"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

log "job $LABEL installed: every week on weekday $weekday at $hour:$(printf '%02d' "$minute")"
log "archives: $backupDir (the newest $keep are kept)"
log "log: $LOG"
log "run it once now:  launchctl kickstart -k gui/$(id -u)/$LABEL"
log "remove it:        launchctl bootout gui/$(id -u)/$LABEL && rm '$PLIST'"
