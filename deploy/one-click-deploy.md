# One-click deploy (Railway · Fly.io · Vercel)

Lower-friction paths to run **Karma Public API** and the **static marketing site** on managed hosts.  
Production still requires you to set secrets, attach Postgres/Redis, and run migrations (wired below where possible).

**Upstream GitHub repo (used in deploy links):** `https://github.com/AtoB101/Karma` — forks should replace this in their own README / docs fork.

## One-click buttons

| Platform | Action |
|----------|--------|
| **Railway** (API) | [![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/new/github?repositories[]=https://github.com/AtoB101/Karma) |
| **Fly.io** (API) | [![Deploy to Fly.io](https://fly.io/button.svg)](https://fly.io/launch?template=https://github.com/AtoB101/Karma) |
| **Vercel** (static `apps/website`) | [![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2FAtoB101%2FKarma&root-directory=apps%2Fwebsite) |

- **Railway:** opens **New project → GitHub** with this repo pre-filled when the `repositories[]` query is honored. After deploy, add **PostgreSQL** + **Redis** plugins and env vars (see below). `railway.toml` supplies Dockerfile path, health check, and `preDeployCommand` migrations.
- **Fly.io:** `fly launch` flow reads **`fly.toml`** at repo root; set `fly secrets` before first deploy. Edit `app = "karma-api-replace-me"` in `fly.toml` if the launcher does not rename it for you.
- **Vercel:** clone flow sets **`root-directory=apps/website`** so only the marketing static tree is deployed.

### Railway Marketplace template (optional)

If maintainers **publish a Railway Template** (workspace → Templates → publish), add a second README button pointing to `https://railway.com/new/template/<TEMPLATE_ID>` (see [Publish and share templates](https://docs.railway.com/templates/publish-and-share)). Until then, the GitHub-prefill button above plus `railway.toml` is the supported path.

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

1. Click **Deploy on Railway** at the top of this doc (or open [railway.com/new](https://railway.com/new) → **Deploy from GitHub repo** → select **AtoB101/Karma**).
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

## Related

- Full stack (Postgres, Redis, MinIO, worker): `deploy/docker-compose.yml`
- Legacy compose Dockerfile (`deploy/Dockerfile.api`) still references Poetry; **PaaS builds should use `deploy/Dockerfile.paas`** until the compose images are aligned.
