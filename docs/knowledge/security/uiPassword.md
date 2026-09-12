# Пароль UI

## [договорённость] Один секрет — `secrets/htpasswd` с bcrypt, читают и nginx, и core

**Контекст:** `init` спрашивает пароль UI на Stage 1, потребители появятся в Stage 4 (auth_basic
в `ui`, API) и Stage 6 (экран входа).
**Суть:** формат — строка `admin:$2b$12$…` (bcrypt, cost 12, пакет `bcrypt` 5.0 с колёсами под
amd64/arm64). `crypt` из стандартной библиотеки удалён в Python 3.13, passlib не сопровождается —
bcrypt единственный живой вариант, а nginx его понимает через `crypt()` musl: проверено на
`nginx:1.31-alpine` — 401 без пароля, 200 с верным, 401 с неверным паролем и с чужим именем.
Грабля при проверке: `return 200` в location срабатывает на фазе rewrite, раньше `auth_basic`, и
«пропускает» любой пароль — проверять на отдаче файла, не на `return`.
**Применение:** Stage 4 — `auth_basic_user_file /etc/nginx/htpasswd` из `secrets/htpasswd`;
core проверяет тот же файл `bcrypt.checkpw`. Один файл, два читателя, один формат.
**Источники:** https://nginx.org/en/docs/http/ngx_http_auth_basic_module.html ,
https://docs.python.org/3.13/whatsnew/3.13.html#removed-modules (crypt удалён),
https://pypi.org/project/bcrypt/ .
