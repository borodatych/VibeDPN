# syntax=docker/dockerfile:1
# UI image: nginx serving the static build and proxying /api/ to core. Until Stage 6 the
# static content is a placeholder page; the nginx configuration is already the real one.
FROM nginx:1.31-alpine
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY placeholder/ /usr/share/nginx/html/
# Installs the password file for /api/ before nginx starts (see the script).
COPY --chmod=755 entrypoint.d/05-htpasswd.sh /docker-entrypoint.d/05-htpasswd.sh
