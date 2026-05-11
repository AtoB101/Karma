# Docker examples

`docker-compose.example.yml` runs an **nginx** static host over the repository root so `/` serves `apps/website`.

```bash
docker compose -f docker/docker-compose.example.yml up --build
```

Open `http://localhost:8080/` (port from compose file).

Copy `docker/.env.example` to a **gitignored** env file for overlays you maintain privately.

## Karma BFF (OpenManus ↔ Karma)

```bash
docker compose -f docker/docker-compose.karma-bff.yml up --build
```

API on `http://127.0.0.1:8820` — set `BFF_INTEGRATION_SECRET` in your shell or `.env` before `docker compose`.
