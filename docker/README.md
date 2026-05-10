# Docker examples

`docker-compose.example.yml` runs an **nginx** static host over the repository root so `/` serves `apps/website`.

```bash
docker compose -f docker/docker-compose.example.yml up --build
```

Open `http://localhost:8080/` (port from compose file).

Copy `docker/.env.example` to a **gitignored** env file for overlays you maintain privately.
