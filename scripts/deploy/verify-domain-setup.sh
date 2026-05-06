#!/usr/bin/env bash
set -euo pipefail

ROOT_DOMAIN="karmapay.cloud"
WWW_DOMAIN="www.${ROOT_DOMAIN}"
APP_DOMAIN="app.${ROOT_DOMAIN}"
API_DOMAIN="api.${ROOT_DOMAIN}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain)
      ROOT_DOMAIN="$2"
      WWW_DOMAIN="www.${ROOT_DOMAIN}"
      APP_DOMAIN="app.${ROOT_DOMAIN}"
      API_DOMAIN="api.${ROOT_DOMAIN}"
      shift 2
      ;;
    --www)
      WWW_DOMAIN="$2"
      shift 2
      ;;
    --app)
      APP_DOMAIN="$2"
      shift 2
      ;;
    --api)
      API_DOMAIN="$2"
      shift 2
      ;;
    *)
      echo "ERR  unknown argument: $1" >&2
      echo "Usage: $0 [--domain karmapay.cloud] [--www www.karmapay.cloud] [--app app.karmapay.cloud] [--api api.karmapay.cloud]" >&2
      exit 1
      ;;
  esac
done

echo "==> DNS + HTTPS quick verification"
for host in "$ROOT_DOMAIN" "$WWW_DOMAIN" "$APP_DOMAIN" "$API_DOMAIN"; do
  echo "-- ${host}"
  echo "A/AAAA:"
  dig +short "$host" A || true
  dig +short "$host" AAAA || true
  echo "HTTP status:"
  curl -s -o /dev/null -w "http:%{http_code}\n" "http://${host}" || true
  curl -s -o /dev/null -w "https:%{http_code}\n" "https://${host}" || true
  echo
done

echo "==> Manual checks"
echo "1) https://${WWW_DOMAIN}/"
echo "2) https://${APP_DOMAIN}/apps/agent-service-guard/frontend/studio/index.html"
echo "3) Browser console should have no 4xx/5xx for JS/CSS"
