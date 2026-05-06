# KarmaPay domain integration (official site + app)

This guide deploys:

- `www.karmapay.cloud` -> marketing/official site
- `app.karmapay.cloud` -> user app (Karma Agent Studio)
- optional `api.karmapay.cloud` -> backend API

It uses a reverse proxy with automatic HTTPS and strict boundary separation.

## 1) DNS records

Point all domains to your server public IP:

- `A @ -> <SERVER_IP>`
- `A www -> <SERVER_IP>`
- `A app -> <SERVER_IP>`
- `A api -> <SERVER_IP>` (optional)

## 2) Build outputs

From repo root:

```bash
mkdir -p /var/www/karmapay-www /var/www/karmapay-app
cp -R apps/agent-service-guard/frontend/* /var/www/karmapay-app/
cp -R . /var/www/karmapay-www-src
```

Then choose the public homepage files you want under `/var/www/karmapay-www`.
For static deployment, keep only the intended marketing assets in that folder.

## 3) Option A: Caddy (recommended for fastest HTTPS)

1. Install Caddy.
2. Copy `infra/caddy/Caddyfile` to `/etc/caddy/Caddyfile`.
3. Edit placeholders:
   - `<SERVER_IP>`
   - backend API target if using `api.karmapay.cloud`.
4. Reload:

```bash
sudo systemctl reload caddy
```

## 4) Option B: Nginx + Certbot

1. Install Nginx + Certbot.
2. Copy `infra/nginx/karmapay.conf` to `/etc/nginx/sites-available/karmapay.conf`.
3. Enable it:

```bash
sudo ln -s /etc/nginx/sites-available/karmapay.conf /etc/nginx/sites-enabled/karmapay.conf
sudo nginx -t
sudo systemctl reload nginx
```

4. Issue certificates:

```bash
sudo certbot --nginx -d karmapay.cloud -d www.karmapay.cloud -d app.karmapay.cloud
```

## 5) Health checks

```bash
curl -I https://www.karmapay.cloud/
curl -I https://app.karmapay.cloud/studio/index.html
```

## 6) Security notes

- Never serve private engine files from public vhost roots.
- Keep secrets in server env/systemd, not frontend bundles.
- For push notifications, frontend should call backend proxy endpoints only.

