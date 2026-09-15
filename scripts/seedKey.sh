#!/usr/bin/env bash
# Seeds an SSH key for a VibeDPN box and lets its account use sudo without a password, so the box
# can then be installed and tuned over the key. Runs on the OWNER'S machine, never on the box.
#
# No password is ever taken from an argument, an environment variable or a file: every password
# prompt belongs to ssh, sudo or su on the box and is answered by the human.
#
# Idempotent: an existing key and alias are reused, ssh-copy-id skips a key the box already has,
# the sudoers file is rewritten with the same content.
set -euo pipefail

readonly DEFAULT_USER=dpn
readonly DEFAULT_HOST=192.168.1.110
readonly DEFAULT_PORT=22
readonly DEFAULT_KEY="$HOME/.ssh/id_ed25519_vibedpn"
readonly DEFAULT_ALIAS=vibedpn

sshUser="${VIBEDPN_SSH_USER:-$DEFAULT_USER}"
sshHost="${VIBEDPN_SSH_HOST:-$DEFAULT_HOST}"
sshPort="${VIBEDPN_SSH_PORT:-$DEFAULT_PORT}"
keyPath="${VIBEDPN_SSH_KEY:-$DEFAULT_KEY}"
sshAlias="${VIBEDPN_SSH_ALIAS:-$DEFAULT_ALIAS}"
fingerprint="${VIBEDPN_HOST_FINGERPRINT:-}"
withSudo=1

say() { printf '%s\n' "$*"; }
fail() {
  printf 'Ошибка: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<TEXT
Засеять SSH-ключ на коробку VibeDPN. Запускается НА ДОМАШНЕЙ МАШИНЕ.

  ./scripts/seedKey.sh [--user dpn] [--host 192.168.1.110] [--port 22]
                       [--key ~/.ssh/id_ed25519_vibedpn] [--alias vibedpn]
                       [--fingerprint SHA256:...] [--no-sudo]

Что делает:
  1. сверяет отпечаток ключа коробки, если он передан (--fingerprint);
  2. создаёт ключ ed25519, если его ещё нет (парольную фразу спросит ssh-keygen);
  3. копирует публичную часть на коробку через ssh-copy-id — пароль учётки вводите вы;
  4. добавляет алиас в ~/.ssh/config;
  5. проверяет вход по ключу без пароля;
  6. разрешает учётке sudo без пароля (/etc/sudoers.d/vibedpn-<учётка>): коробку дальше ставят
     и настраивают по ключу. Пароль sudo или root спросит сама коробка. --no-sudo — пропустить.

Переменные окружения: VIBEDPN_SSH_USER, VIBEDPN_SSH_HOST, VIBEDPN_SSH_PORT, VIBEDPN_SSH_KEY,
VIBEDPN_SSH_ALIAS, VIBEDPN_HOST_FINGERPRINT.
TEXT
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --user)
      sshUser="${2:-}"
      shift 2
      ;;
    --host)
      sshHost="${2:-}"
      shift 2
      ;;
    --port)
      sshPort="${2:-}"
      shift 2
      ;;
    --key)
      keyPath="${2:-}"
      shift 2
      ;;
    --alias)
      sshAlias="${2:-}"
      shift 2
      ;;
    --fingerprint)
      fingerprint="${2:-}"
      shift 2
      ;;
    --no-sudo)
      withSudo=0
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *) fail "Неизвестный аргумент: $1 (--help покажет список)" ;;
  esac
done

[ -n "$sshUser" ] || fail "Пустое имя пользователя"
[ -n "$sshHost" ] || fail "Пустой адрес коробки"
[ -n "$sshPort" ] || fail "Пустой порт"
[ -n "$keyPath" ] || fail "Пустой путь к ключу"
[ -n "$sshAlias" ] || fail "Пустой алиас"
case "$sshUser" in
  *[!a-z0-9_-]*) fail "Имя учётки «$sshUser»: только строчные латинские буквы, цифры, _ и -" ;;
esac

# Preconditions: everything this script leans on must exist before the first side effect.
for tool in ssh ssh-keygen ssh-copy-id ssh-keyscan; do
  command -v "$tool" >/dev/null 2>&1 ||
    fail "Не найдена команда «$tool». На macOS ssh-copy-id ставится так: brew install ssh-copy-id"
done

say "Коробка: ${sshUser}@${sshHost}:${sshPort}"
say "Ключ:    ${keyPath}"
say "Алиас:   ${sshAlias}"
say ""

# 1. The box is the one the owner means: a fingerprint read from its console beats trust on first use.
if [ -n "$fingerprint" ]; then
  say "1/6 Сверяю отпечаток ключа коробки…"
  scanned="$(ssh-keyscan -T 10 -p "$sshPort" "$sshHost" 2>/dev/null | ssh-keygen -lf - 2>/dev/null |
    awk '{ print $2 }')"
  printf '%s\n' "$scanned" | grep -qxF "$fingerprint" ||
    fail "Отпечаток коробки не совпал с ${fingerprint}: получено «${scanned:-ничего}». Проверьте адрес"
  say "    Совпал."
else
  say "1/6 Отпечаток не передан (--fingerprint): ssh покажет его сам — сверьте с консолью коробки."
fi
say ""

# 2. Key pair.
mkdir -p "$(dirname "$keyPath")"
chmod 700 "$(dirname "$keyPath")"
if [ -f "$keyPath" ]; then
  say "2/6 Ключ уже есть — использую существующий, не перезаписываю."
else
  say "2/6 Создаю ключ. Придумайте парольную фразу (Enter — без неё)."
  say "    Скрипт её не видит и нигде не сохраняет."
  ssh-keygen -t ed25519 -a 100 -C "vibedpn@$(hostname -s)" -f "$keyPath"
fi
[ -f "${keyPath}.pub" ] || fail "Нет публичной части ${keyPath}.pub — удалите ${keyPath} и повторите"
say ""

# 3. Copy the public half. ssh-copy-id prompts for the account password itself and skips a key
# the box already has, so re-running is harmless.
say "3/6 Копирую публичный ключ на коробку. Пароль учётки ${sshUser} спросит ssh."
ssh-copy-id -i "${keyPath}.pub" -p "$sshPort" "${sshUser}@${sshHost}"
say ""

# 4. Host alias, so every later step is just `ssh <alias>`.
config="$HOME/.ssh/config"
touch "$config"
chmod 600 "$config"
if grep -qiE "^host[[:space:]]+${sshAlias}([[:space:]]|$)" "$config"; then
  say "4/6 Алиас «${sshAlias}» уже в ~/.ssh/config — не трогаю."
else
  say "4/6 Добавляю алиас «${sshAlias}» в ~/.ssh/config."
  cat >>"$config" <<EOF

Host ${sshAlias}
    HostName ${sshHost}
    User ${sshUser}
    Port ${sshPort}
    IdentityFile ${keyPath}
    IdentitiesOnly yes
EOF
fi
say ""

# 5. Key-only login, no password fallback, no interactive prompt.
keyOnly=(-i "$keyPath" -p "$sshPort" -o IdentitiesOnly=yes -o PreferredAuthentications=publickey)
say "5/6 Проверяю вход по ключу (пароль намеренно запрещён)…"
ssh "${keyOnly[@]}" -o BatchMode=yes "${sshUser}@${sshHost}" 'echo ok' | grep -qx ok ||
  fail "Вход по ключу не удался. Проверьте, что на коробке разрешён publickey-вход, и повторите."
say "    Вход по ключу работает."
say ""

# 6. sudo without a password for this account: the box is a dedicated device installed over the key.
if [ "$withSudo" -eq 0 ]; then
  say "6/6 Пропускаю sudo (--no-sudo)."
elif ssh "${keyOnly[@]}" -o BatchMode=yes "${sshUser}@${sshHost}" 'sudo -n true' 2>/dev/null; then
  say "6/6 sudo без пароля уже работает."
else
  say "6/6 Разрешаю ${sshUser} sudo без пароля."
  say "    Если sudo на коробке есть и ${sshUser} в группе sudo — спросит пароль ${sshUser}."
  say "    Если нет — спросит пароль root: поставлю sudo и добавлю ${sshUser} в группу."
  # One remote script, run as root either way; visudo checks the file before it is put in place.
  grant="set -eu
command -v sudo >/dev/null 2>&1 || { apt-get update -q && apt-get install -y -q sudo; }
usermod -aG sudo ${sshUser}
tmp=\$(mktemp)
printf '%s\n' '${sshUser} ALL=(ALL:ALL) NOPASSWD: ALL' >\"\$tmp\"
visudo -cf \"\$tmp\" >/dev/null
install -m 0440 -o root -g root \"\$tmp\" /etc/sudoers.d/vibedpn-${sshUser}
rm -f \"\$tmp\""
  if ssh "${keyOnly[@]}" -o BatchMode=yes "${sshUser}@${sshHost}" 'command -v sudo >/dev/null && id -nG | grep -qw sudo'; then
    ssh -t "${keyOnly[@]}" "${sshUser}@${sshHost}" "sudo sh -c '$(printf '%s' "$grant" | sed "s/'/'\\\\''/g")'"
  else
    ssh -t "${keyOnly[@]}" "${sshUser}@${sshHost}" "su - root -c '$(printf '%s' "$grant" | sed "s/'/'\\\\''/g")'"
  fi
  ssh "${keyOnly[@]}" -o BatchMode=yes "${sshUser}@${sshHost}" 'sudo -n true' ||
    fail "sudo без пароля так и не заработал: проверьте /etc/sudoers.d/vibedpn-${sshUser} на коробке"
  say "    sudo без пароля работает."
fi
say ""

say "Готово: «ssh ${sshAlias}» входит по ключу. Дальше коробку ставят по нему (docs/manuals/installation.md)."
