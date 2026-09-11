# syntax=docker/dockerfile:1
# UI image: nginx serving the static build and proxying /api/ to core. Until Stage 6 the
# static content is a placeholder page; the nginx configuration is already the real one.
FROM nginx:1.31-alpine
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY placeholder/ /usr/share/nginx/html/
