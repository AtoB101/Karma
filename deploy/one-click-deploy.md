# One-click deploy (Railway · Fly.io · Vercel)

Lower-friction paths to run **Karma Public API** and the **static marketing site** on managed hosts.  
Production still requires you to set secrets, attach Postgres/Redis, and run migrations (wired below where possible).

## What ships in this repo

| Artifact | Purpose |
|----------|---------|
| `deploy/Dockerfile.paas` | API image: `pip install .`, `uvicorn`, honors `PORT` |
| `railway.toml` | Railway: Dockerfile build, `/health` check, **pre-deploy migrations** |
| `fly.toml` | Fly Machines: same Dockerfile, **release_command** migrations, `PORT=8080` |
| `apps/website/vercel.json` | Vercel static headers / clean URLs for the marketing site |

**Celery worker**, **MinIO**, and **private risk runtime** are not in these templates—add a second service or use managed object storage (S3-compatible) per your security model.

---

## Environment (all platforms)

Set at least (names match `config/settings.py` / `.env` conventions — use UPPER_SNAKE in hosts):

| Variable | Notes |
|----------|--------|
| `DATABASE_URL` | e.g. `postgresql+asyncpg://user:pass@host:5432/dbname` |
| `REDIS_URL` | e.g. `redis://default:pass@host:6379/0` |
| `APP_SECRET_KEY` | Strong random string |
| `AUTH_API_KEYS` | Comma-separated `agent:secret` for API-key auth |
| `AUTH_ENFORCE_PROTECTED_ROUTES` | `true` in production |
| `CORS_ALLOW_ORIGINS` | Your Console / site origins, comma-separated |
| `MINIO_*` or future S3-compatible settings | Evidence storage — use a managed bucket in production |

Generate signing keys locally (`python scripts/generate_keys.py`) and mount or inject paths if you do not bake keys into the image (recommended: secrets + volume).

---

## Railway (API)

1. Open [railway.app/new](https://railway.app/new) → **Deploy from GitHub repo** → select this repository.
2. Add plugins: **PostgreSQL**, **Redis** (and optional Redis DB indices for Celery if you add a worker service later).
3. Map plugin connection strings to `DATABASE_URL` and `REDIS_URL` (async URL form as above).
4. Set the rest of the env vars from the table.
5. Deploy: Railway reads **`railway.toml`** — build uses **`deploy/Dockerfile.paas`**, **`preDeployCommand`** runs `alembic upgrade head`, health check hits **`/health`**.

**Note:** If the dashboard also sets a start command, leave it empty so the image **`CMD`** (`uvicorn` + `PORT`) is used.

---

## Fly.io (API)

1. Install the [Fly CLI](https://fly.io/docs/hands-on/install-flyctl/).
2. Edit **`fly.toml`**: replace `app = "karma-api-replace-me"` with your app name.
3. `fly apps create <your-app-name>` (if new).
4. `fly secrets set DATABASE_URL=... REDIS_URL=... APP_SECRET_KEY=... AUTH_API_KEYS=...`
5. `fly deploy`

`release_command` runs migrations before traffic. **`PORT`** is set to **8080** in `[env]` to match **`internal_port`**.

---

## Vercel (static marketing site)

The API is **not** suited to Vercel Serverless as-is (long-lived FastAPI + WebSockets/Celery patterns). Deploy **only** the static site:

1. [vercel.com/new](https://vercel.com/new) → Import this repository.
2. **Root Directory:** `apps/website`
3. Framework preset: **Other** (static HTML/CSS).
4. Build command: leave empty or `echo "static"`.
5. Output directory: `.` (default when root is `apps/website`).

`apps/website/vercel.json` adds basic security headers. Update links in HTML if the developer portal is hosted elsewhere.

---

## Optional: template buttons

Hosted **“Deploy to Railway”** buttons require a **template** published under a Railway account; this repo ships **config-as-code** (`railway.toml`) instead so any fork can connect without a central template URL. You can still add a button later via [Railway Template docs](https://docs.railway.app/guides/publish-templates).

---

## Related

- Full stack (Postgres, Redis, MinIO, worker): `deploy/docker-compose.yml`
- Legacy compose Dockerfile (`deploy/Dockerfile.api`) still references Poetry; **PaaS builds should use `deploy/Dockerfile.paas`** until the compose images are aligned.
