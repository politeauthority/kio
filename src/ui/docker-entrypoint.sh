#!/bin/sh
set -e

# Inject runtime config into index.html so the container image stays environment-agnostic.
API_URL="${API_URL:-}"
OIDC_AUTHORITY="${OIDC_AUTHORITY:-}"
OIDC_CLIENT_ID="${OIDC_CLIENT_ID:-}"
KIO_BRANCH="${KIO_BRANCH:-}"

sed -i \
  -e "s|__API_URL__|${API_URL}|g" \
  -e "s|__OIDC_AUTHORITY__|${OIDC_AUTHORITY}|g" \
  -e "s|__OIDC_CLIENT_ID__|${OIDC_CLIENT_ID}|g" \
  -e "s|__KIO_BRANCH__|${KIO_BRANCH}|g" \
  /usr/share/nginx/html/index.html

exec "$@"
