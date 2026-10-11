#!/usr/bin/env bash
# Deploy the Karma outbound-mail relay gateway to an offshore host.
#
# Why an offshore host
# --------------------
# The mainland box cannot reliably reach Gmail/Outlook SMTP (GFW jitter), and
# outbound port 25 is blocked outright. So "must reach the outside SMTP" moves
# OFF the mainland box: this gateway lives outside the GFW, terminates TLS on
# 443 only (Caddy), and relays through the host's own SMTP. The mainland backend
# then talks plain HTTPS(443) to it -- see services/mailer.py::_send_via_relay.
#
# Usage
# -----
#   GATEWAY_HOST=root@1.2.3.4 \
#   GATEWAY_SSH_KEY=~/.ssh/id_ed25519 \
#   GATEWAY_DOMAIN=mail-relay.example.com \
#     bash scripts/ops/deploy_mail_gateway.sh
#
# Required env:
#   GATEWAY_HOST             user@host of the offshore box
#   GATEWAY_SSH_KEY          private key path for that host
#   GATEWAY_DOMAIN           public hostname Caddy gets a real 443 cert for
#
# Optional env:
#   KARMA_MAIL_RELAY_TOKEN   shared bearer token; minted here if unset
#   GATEWAY_MAIL_FROM        envelope sender   (default karma@$GATEWAY_DOMAIN)
#   GATEWAY_SMTP_HOST/PORT   upstream SMTP     (default 127.0.0.1:25)
#   GATEWAY_SMTP_USER/PASSWORD
#   GATEWAY_SMTP_STARTTLS    default 1 (587)
#   GATEWAY_SMTP_SSL         default 0 (465)
#   GATEWAY_PORT             local gateway port (default 8080)
#   GATEWAY_REMOTE_DIR       remote install dir (default /opt/karma-mail-gateway)
#
# Exit codes: 0 ok; 2 missing/invalid env or source; 3 remote step failed.
set -euo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SELF_DIR}/../.." && pwd)"
GATEWAY_SRC="${REPO_DIR}/scripts/ops/mail_gateway.py"

GATEWAY_HOST="${GATEWAY_HOST:-}"
GATEWAY_SSH_KEY="${GATEWAY_SSH_KEY:-}"
GATEWAY_DOMAIN="${GATEWAY_DOMAIN:-}"
GATEWAY_PORT="${GATEWAY_PORT:-8080}"
GATEWAY_REMOTE_DIR="${GATEWAY_REMOTE_DIR:-/opt/karma-mail-gateway}"
GATEWAY_MAIL_FROM="${GATEWAY_MAIL_FROM:-}"
GATEWAY_SMTP_HOST="${GATEWAY_SMTP_HOST:-127.0.0.1}"
GATEWAY_SMTP_PORT="${GATEWAY_SMTP_PORT:-25}"
GATEWAY_SMTP_USER="${GATEWAY_SMTP_USER:-}"
GATEWAY_SMTP_PASSWORD="${GATEWAY_SMTP_PASSWORD:-}"
GATEWAY_SMTP_STARTTLS="${GATEWAY_SMTP_STARTTLS:-1}"
GATEWAY_SMTP_SSL="${GATEWAY_SMTP_SSL:-0}"

say() { printf '%s\n' "$*"; }
die() { printf 'deploy_mail_gateway: %s\n' "$*" >&2; exit "${2:-3}"; }

# Fail closed on missing inputs -- same philosophy as the repo's secrets gate.
[ -n "${GATEWAY_HOST}" ]    || die "missing required env: GATEWAY_HOST (user@host)" 2
[ -n "${GATEWAY_SSH_KEY}" ] || die "missing required env: GATEWAY_SSH_KEY (private key path)" 2
[ -n "${GATEWAY_DOMAIN}" ]  || die "missing required env: GATEWAY_DOMAIN (Caddy needs a real hostname for 443)" 2
[ -f "${GATEWAY_SSH_KEY}" ] || die "GATEWAY_SSH_KEY is not a file: ${GATEWAY_SSH_KEY}" 2
[ -f "${GATEWAY_SRC}" ]     || die "gateway source not found: ${GATEWAY_SRC}" 2
command -v ssh >/dev/null 2>&1 || die "ssh not found on PATH" 2
command -v scp >/dev/null 2>&1 || die "scp not found on PATH" 2

[ -n "${GATEWAY_MAIL_FROM}" ] || GATEWAY_MAIL_FROM="karma@${GATEWAY_DOMAIN}"

TOKEN="${KARMA_MAIL_RELAY_TOKEN:-}"
GENERATED=0
if [ -z "${TOKEN}" ]; then
  TOKEN="$(od -An -tx1 -N32 /dev/urandom | tr -d ' \n')"
  GENERATED=1
fi

SSH=(ssh -i "${GATEWAY_SSH_KEY}" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 "${GATEWAY_HOST}")
SCP=(scp -i "${GATEWAY_SSH_KEY}" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

cp "${GATEWAY_SRC}" "${TMP_DIR}/mail_gateway.py"

# gateway.env -- 0600 on the remote, and never echoed back by this script.
umask 077
cat > "${TMP_DIR}/gateway.env" <<ENV
KARMA_GATEWAY_TOKEN=${TOKEN}
KARMA_GATEWAY_BIND=127.0.0.1
KARMA_GATEWAY_PORT=${GATEWAY_PORT}
KARMA_GATEWAY_SMTP_HOST=${GATEWAY_SMTP_HOST}
KARMA_GATEWAY_SMTP_PORT=${GATEWAY_SMTP_PORT}
KARMA_GATEWAY_SMTP_USER=${GATEWAY_SMTP_USER}
KARMA_GATEWAY_SMTP_PASSWORD=${GATEWAY_SMTP_PASSWORD}
KARMA_GATEWAY_SMTP_FROM=${GATEWAY_MAIL_FROM}
KARMA_GATEWAY_SMTP_STARTTLS=${GATEWAY_SMTP_STARTTLS}
KARMA_GATEWAY_SMTP_SSL=${GATEWAY_SMTP_SSL}
ENV

cat > "${TMP_DIR}/Caddyfile" <<CADDY
{
	admin off
}

${GATEWAY_DOMAIN} {
	reverse_proxy 127.0.0.1:${GATEWAY_PORT}
}
CADDY

cat > "${TMP_DIR}/karma-mail-gateway.service" <<UNIT
[Unit]
Description=Karma outbound mail relay gateway
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${GATEWAY_REMOTE_DIR}
Environment=GATEWAY_ENV=${GATEWAY_REMOTE_DIR}/gateway.env
ExecStart=/usr/bin/python3 ${GATEWAY_REMOTE_DIR}/mail_gateway.py
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadOnlyPaths=${GATEWAY_REMOTE_DIR}

[Install]
WantedBy=multi-user.target
UNIT

cat > "${TMP_DIR}/install.sh" <<INSTALL
#!/usr/bin/env bash
set -euo pipefail
DIR="${GATEWAY_REMOTE_DIR}"
if ! command -v caddy >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl gnupg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -y
  apt-get install -y caddy
fi
chmod 600 "\$DIR/gateway.env"
install -m 0644 "\$DIR/Caddyfile" /etc/caddy/Caddyfile
install -m 0644 "\$DIR/karma-mail-gateway.service" /etc/systemd/system/karma-mail-gateway.service
systemctl daemon-reload
systemctl enable --now karma-mail-gateway
systemctl restart karma-mail-gateway
systemctl enable --now caddy
systemctl reload caddy 2>/dev/null || systemctl restart caddy
python3 "\$DIR/mail_gateway.py" --check
INSTALL

say "==> uploading to ${GATEWAY_HOST}:${GATEWAY_REMOTE_DIR}"
"${SSH[@]}" "mkdir -p '${GATEWAY_REMOTE_DIR}'" || die "cannot reach ${GATEWAY_HOST}" 3
"${SCP[@]}" "${TMP_DIR}/mail_gateway.py" "${TMP_DIR}/gateway.env" "${TMP_DIR}/Caddyfile" \
  "${TMP_DIR}/karma-mail-gateway.service" "${TMP_DIR}/install.sh" \
  "${GATEWAY_HOST}:${GATEWAY_REMOTE_DIR}/" || die "upload failed" 3

say "==> installing on the remote host"
"${SSH[@]}" "chmod 600 '${GATEWAY_REMOTE_DIR}/gateway.env'; sudo bash '${GATEWAY_REMOTE_DIR}/install.sh'" \
  || die "remote install failed" 3

say ""
say "==> done. On the mainland box, add to /opt/karma/.env and recreate the app:"
say "    KARMA_MAIL_RELAY_URL=https://${GATEWAY_DOMAIN}/send"
if [ "${GENERATED}" = "1" ]; then
  say "    KARMA_MAIL_RELAY_TOKEN=${TOKEN}    # generated just now -- treat it as a secret"
else
  say "    KARMA_MAIL_RELAY_TOKEN=<the token you passed in>"
fi
say ""
say "    docker compose --env-file /opt/karma/.env -f deploy/docker-compose.yml up -d --no-build app"
