# Karma — Deployment SOP

## Prerequisites

- Docker + Docker Compose v2
- Python 3.11+
- PostgreSQL 16 (managed via Docker)
- Redis 7 (managed via Docker)
- MinIO (managed via Docker)

---

## 1. First-time Setup

```bash
# Clone
git clone https://github.com/your-org/karma-public.git
cd karma-public

# Copy env
cp .env.example .env
# Edit .env: set APP_SECRET_KEY, OPENAI_API_KEY, PRIVATE_RUNTIME_URL

# Generate Ed25519 keys (auto-generated on first run, or manually:)
mkdir -p keys
python -c "
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
k = Ed25519PrivateKey.generate()
open('keys/agent_private.pem','wb').write(k.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
))
open('keys/agent_public.pem','wb').write(k.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
))
print('Keys generated.')
"
```

---

## 2. Start Infrastructure

```bash
docker compose -f deploy/docker-compose.yml up -d postgres redis minio
# Wait for health checks
docker compose -f deploy/docker-compose.yml ps
```

---

## 3. Run Database Migrations

```bash
pip install alembic asyncpg
alembic upgrade head
```

---

## 4. Create MinIO Buckets

```bash
# Install MinIO client
pip install minio
python -c "
from minio import Minio
c = Minio('localhost:9000', 'minioadmin', 'minioadmin', secure=False)
for b in ['karma-evidence', 'karma-receipts']:
    if not c.bucket_exists(b): c.make_bucket(b)
    print(f'Bucket {b} ready')
"
```

---

## 5. Start All Services

```bash
docker compose -f deploy/docker-compose.yml up -d
```

Services started:
- `api` → http://localhost:8000 (docs: http://localhost:8000/docs)
- `worker` → Celery worker (verification, settlement, reputation queues)
- `prometheus` → http://localhost:9090
- `grafana` → http://localhost:3000 (admin/admin)

---

## 6. Start Private Runtime (separate repo, internal network only)

```bash
# In karma-private repo
cp .env.private.example .env.private
# Edit: set RUNTIME_API_KEY (must match PUBLIC .env PRIVATE_RUNTIME_API_KEY)
python main.py
# Starts on 127.0.0.1:8001
```

---

## 7. Verify Deployment

```bash
# Health check
curl http://localhost:8000/health

# Register a test agent
curl -X POST http://localhost:8000/v1/agents \
  -H "Content-Type: application/json" \
  -d '{"name":"Test","role":"worker"}'

# Run demo
python examples/demo_captioning.py
```

---

## 8. Production Checklist

- [ ] `APP_SECRET_KEY` set to random 32+ char string
- [ ] `PRIVATE_RUNTIME_API_KEY` set and matches private runtime
- [ ] Ed25519 keys generated and backed up
- [ ] PostgreSQL password changed from default
- [ ] MinIO credentials changed from default
- [ ] Private runtime bound to `127.0.0.1` only (never public)
- [ ] TLS termination configured (nginx/caddy in front of API)
- [ ] Prometheus alerts configured
- [ ] Database backups scheduled

---

## 9. Scaling

**More API workers:**
```bash
docker compose up -d --scale api=3
```

**More Celery workers (verification is CPU-heavy):**
```bash
docker compose up -d --scale worker=4
```

**Worker queue separation:**
```bash
# Dedicated verification workers
celery -A worker.tasks worker -Q verification --concurrency=8

# Dedicated settlement workers  
celery -A worker.tasks worker -Q settlement,reputation --concurrency=4
```

---

## 10. Monitoring

| Metric | Alert threshold |
|--------|----------------|
| `karma_http_requests_total{status="5xx"}` | > 1% of traffic |
| `karma_http_request_duration_seconds{p99}` | > 2s |
| Celery queue depth (`verification`) | > 100 |
| PostgreSQL connections | > 80% of pool |

---

## Rollback

```bash
alembic downgrade -1
docker compose pull
docker compose up -d
```
