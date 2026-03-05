# Docker Build Guide — CephS3Manager-Web

Complete reference for building, running, and deploying CephS3Manager-Web with Docker.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Project layout](#project-layout)
3. [Dockerfile explained](#dockerfile-explained)
4. [Building the image](#building-the-image)
5. [Running with plain Docker](#running-with-plain-docker)
6. [Running with Docker Compose](#running-with-docker-compose)
7. [Environment variables](#environment-variables)
8. [Persistent data (volumes)](#persistent-data-volumes)
9. [Health check](#health-check)
10. [Multi-platform builds](#multi-platform-builds)
11. [Pushing to a registry](#pushing-to-a-registry)
12. [Kubernetes deployment](#kubernetes-deployment)
13. [Troubleshooting](#troubleshooting)

---

## Prerequisites

| Tool | Minimum version | Check |
|------|----------------|-------|
| Docker | 24.0 | `docker --version` |
| Docker Compose | 2.20 (plugin) | `docker compose version` |
| (optional) BuildKit | enabled by default in Docker 23+ | `docker buildx version` |

---

## Project layout

```
s3mangerkuber/
├── Dockerfile            ← two-stage build definition
├── docker-compose.yml    ← local dev / single-host deploy
├── requirements.txt      ← Python dependencies
├── main.py               ← application entry point
├── app/                  ← pages, models, s3 client, …
└── k8s/                  ← Kubernetes manifests
    ├── deployment.yaml   ← Deployment + PVC + Secret
    ├── service.yaml      ← ClusterIP Service + Ingress
    └── configmap.yaml    ← env-var ConfigMap
```

---

## Dockerfile explained

```dockerfile
# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.13-slim AS builder
```
Uses the official slim Python 3.13 image as the build base.
`AS builder` names this stage so the runtime stage can copy from it.

```dockerfile
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*
```
`gcc` is required to compile certain C-extension wheels (e.g. `aiosqlite`, `uvloop`).
The `rm -rf /var/lib/apt/lists/*` removes the package index cache immediately,
keeping the **builder** layer small.

```dockerfile
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --prefix=/install --no-cache-dir -r requirements.txt
```
`--prefix=/install` installs all packages into `/install` instead of the system
Python prefix. This isolated directory is later copied wholesale into the runtime
image — nothing else from the builder leaks across.
`--no-cache-dir` prevents pip from writing a cache, saving ~30 MB per build.

```dockerfile
# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.13-slim AS runtime
```
Fresh, clean base. No build tools, no gcc, no cached apt lists — only what's
needed to run the app.

```dockerfile
LABEL org.opencontainers.image.title="CephS3Manager-Web"
LABEL org.opencontainers.image.description="Modern S3 + Ceph RGW admin tool"
```
OCI image labels — visible in `docker inspect` and most registry UIs.

```dockerfile
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    APP_HOST=0.0.0.0 \
    APP_PORT=8080
```

| Variable | Purpose |
|----------|---------|
| `PYTHONDONTWRITEBYTECODE=1` | Skip `.pyc` files — faster startup, smaller layer |
| `PYTHONUNBUFFERED=1` | Flush stdout/stderr immediately → logs appear in `docker logs` in real time |
| `DATA_DIR=/data` | Directory for the SQLite database and uploads |
| `APP_HOST=0.0.0.0` | Bind on all interfaces inside the container |
| `APP_PORT=8080` | Port the uvicorn server listens on |

```dockerfile
WORKDIR /app
COPY --from=builder /install /usr/local
COPY . .
```
First `COPY` pulls the pre-built packages from the builder stage.
Second `COPY` adds the application source code.
Order matters: packages change less often than source, so Docker can reuse
the first `COPY` layer across builds.

```dockerfile
RUN mkdir -p /data && \
    addgroup --system appgroup && \
    adduser  --system --ingroup appgroup appuser && \
    chown -R appuser:appgroup /app /data
USER appuser
```
Creates a non-root system user `appuser`. Running as non-root is a security
requirement for most Kubernetes clusters (`runAsNonRoot: true`) and a
Docker best practice.

```dockerfile
EXPOSE 8080
```
Documents that the container listens on 8080. Does not actually publish the
port — that's done at `docker run -p` time.

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/')"
```
Docker polls the app every 30 s. After 3 consecutive failures it marks the
container `unhealthy`. Docker Compose and Kubernetes (via readiness probes)
use this to decide whether to send traffic.

```dockerfile
CMD ["python", "main.py"]
```
Default command. Override at `docker run` time if needed.

---

## Building the image

### Basic build

```bash
# From the project root (where Dockerfile lives)
docker build -t cephs3manager-web:latest .
```

### Build with a specific version tag

```bash
docker build -t cephs3manager-web:1.0.0 -t cephs3manager-web:latest .
```

### Build without using the cache (force full rebuild)

```bash
docker build --no-cache -t cephs3manager-web:latest .
```

### Build with BuildKit progress output (nicer logs)

```bash
DOCKER_BUILDKIT=1 docker build --progress=plain -t cephs3manager-web:latest .
```

### Inspect image size

```bash
docker images cephs3manager-web
# REPOSITORY             TAG       IMAGE ID       CREATED        SIZE
# cephs3manager-web      latest    a1b2c3d4e5f6   2 minutes ago  ~320MB
```

### Inspect layer breakdown

```bash
docker history cephs3manager-web:latest
```

---

## Running with plain Docker

### Minimal run (data is lost on container removal)

```bash
docker run -d \
  -p 8080:8080 \
  -e STORAGE_SECRET="$(openssl rand -hex 32)" \
  --name cephs3manager \
  cephs3manager-web:latest
```

Open **http://localhost:8080** in your browser.

### Run with a named volume (data persists across restarts)

```bash
docker volume create cephs3mgr_data

docker run -d \
  -p 8080:8080 \
  -v cephs3mgr_data:/data \
  -e STORAGE_SECRET="$(openssl rand -hex 32)" \
  -e LOG_LEVEL=INFO \
  --name cephs3manager \
  --restart unless-stopped \
  cephs3manager-web:latest
```

### View logs

```bash
docker logs -f cephs3manager
```

### Stop and remove

```bash
docker stop cephs3manager
docker rm cephs3manager
```

### Enter the running container (for debugging)

```bash
docker exec -it cephs3manager /bin/sh
```

---

## Running with Docker Compose

`docker-compose.yml` is already included. It builds the image locally,
mounts a named volume, and sets all required environment variables.

### Start

```bash
docker compose up -d
```

This will:
1. Build the image if it doesn't exist
2. Create the `cephs3mgr_data` volume if it doesn't exist
3. Start the container in the background

### Force rebuild after code changes

```bash
docker compose up -d --build
```

### View logs

```bash
docker compose logs -f
```

### Stop (keeps data volume)

```bash
docker compose down
```

### Stop and delete data volume (complete reset)

```bash
docker compose down -v
```

---

## Environment variables

All variables can be passed via `-e KEY=VALUE` (plain Docker) or under
`environment:` in `docker-compose.yml`.

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `STORAGE_SECRET` | `cephs3mgr-change-me-in-prod` | **Yes** (in prod) | NiceGUI session cookie signing key. Use `openssl rand -hex 32` to generate. |
| `DATA_DIR` | `/data` (container) / `~/.cephs3mgr` (dev) | No | Directory for SQLite DB and upload temp files. |
| `APP_HOST` | `0.0.0.0` | No | Uvicorn bind address. |
| `APP_PORT` | `8080` | No | Uvicorn port. |
| `DEFAULT_REGION` | `us-east-1` | No | Default S3 region shown in the connection dialog. |
| `MAX_UPLOAD_SIZE_MB` | `5120` | No | Maximum upload size in megabytes (5 GB default). |
| `LOG_LEVEL` | `INFO` | No | Python log level. Set to `DEBUG` for verbose output. |
| `DEV_RELOAD` | `false` | No | Enable NiceGUI hot-reload. **Never use in production.** |

### Generating a strong secret

```bash
# Linux / macOS
openssl rand -hex 32

# Python (if openssl not available)
python3 -c "import secrets; print(secrets.token_hex(32))"
```

---

## Persistent data (volumes)

The application stores two types of data under `DATA_DIR` (`/data` inside the container):

| Path | Content |
|------|---------|
| `/data/cephs3mgr.db` | SQLite database — saved connections, settings |
| `/data/uploads/` | Temporary upload staging area |

**Always mount `/data` as a volume.** Without a volume, every container restart
wipes all saved connections.

```bash
# Named volume (recommended)
-v cephs3mgr_data:/data

# Bind mount to a host directory (useful for backups)
-v /opt/cephs3mgr/data:/data
```

### Backup the database

```bash
# Copy the DB out of the running container
docker cp cephs3manager:/data/cephs3mgr.db ./cephs3mgr_backup.db

# Or from a named volume (container can be stopped)
docker run --rm \
  -v cephs3mgr_data:/data \
  -v "$(pwd)":/backup \
  busybox cp /data/cephs3mgr.db /backup/cephs3mgr_backup.db
```

### Restore the database

```bash
docker cp ./cephs3mgr_backup.db cephs3manager:/data/cephs3mgr.db
docker restart cephs3manager
```

---

## Health check

Docker's built-in health check fires every 30 seconds and marks the container
`healthy` / `unhealthy`:

```bash
# Watch health status
docker ps --format "table {{.Names}}\t{{.Status}}"
# NAME              STATUS
# cephs3manager     Up 3 minutes (healthy)
```

You can also inspect the last health check result:

```bash
docker inspect --format='{{json .State.Health}}' cephs3manager | python3 -m json.tool
```

---

## Multi-platform builds

To build for both `linux/amd64` (x86 servers) and `linux/arm64` (Apple M-series, AWS Graviton):

```bash
# One-time setup: create a multi-platform builder
docker buildx create --name multibuilder --use

# Build and push (must push for multi-arch manifests)
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t yourrepo/cephs3manager-web:latest \
  --push \
  .
```

To build locally for the current machine only:

```bash
docker buildx build --load -t cephs3manager-web:latest .
```

---

## Pushing to a registry

### Docker Hub

```bash
# Tag
docker tag cephs3manager-web:latest youruser/cephs3manager-web:latest

# Push
docker login
docker push youruser/cephs3manager-web:latest
```

### GitHub Container Registry (ghcr.io)

```bash
echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin

docker tag cephs3manager-web:latest ghcr.io/youruser/cephs3manager-web:latest
docker push ghcr.io/youruser/cephs3manager-web:latest
```

### Private registry (e.g. Harbor, GitLab)

```bash
docker tag cephs3manager-web:latest registry.example.com/cephs3manager-web:1.0.0
docker push registry.example.com/cephs3manager-web:1.0.0
```

---

## Kubernetes deployment

The `k8s/` directory contains ready-to-apply manifests.

### 1. Generate a strong secret

```bash
kubectl create secret generic cephs3manager-secret \
  --namespace default \
  --from-literal=storage-secret="$(openssl rand -hex 32)"
```

Or edit `k8s/deployment.yaml` and replace the placeholder in the `Secret` block
before applying.

### 2. Set your image in deployment.yaml

Edit `k8s/deployment.yaml` and update the image field:

```yaml
containers:
  - name: cephs3manager
    image: yourrepo/cephs3manager-web:latest   # ← change this
    imagePullPolicy: Always                     # use Always when pushing to a remote registry
```

### 3. Set your StorageClass

In `k8s/deployment.yaml`, find the `PersistentVolumeClaim` section and set the
correct `storageClassName` for your cluster:

```yaml
storageClassName: standard          # Kind / minikube
# storageClassName: rook-ceph-block # Rook-Ceph
# storageClassName: gp3             # AWS EKS
# storageClassName: premium-rwo     # GKE
```

### 4. Set your hostname in service.yaml

```yaml
rules:
  - host: s3manager.example.com   # ← change this
```

### 5. Apply everything

```bash
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
```

### 6. Verify

```bash
# Watch rollout
kubectl rollout status deployment/cephs3manager

# Check pods
kubectl get pods -l app=cephs3manager

# Tail logs
kubectl logs -f deployment/cephs3manager

# Port-forward for quick local access (no Ingress needed)
kubectl port-forward deployment/cephs3manager 8080:8080
```

### Enable TLS with cert-manager

Add to the Ingress in `k8s/service.yaml`:

```yaml
metadata:
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  tls:
    - hosts:
        - s3manager.example.com
      secretName: cephs3manager-tls
```

---

## Troubleshooting

### Container exits immediately

```bash
docker logs cephs3manager
```

Common causes:

| Error message | Fix |
|---------------|-----|
| `ModuleNotFoundError` | Rebuild the image: `docker build --no-cache` |
| `Permission denied: '/data'` | Mount a writable volume: `-v cephs3mgr_data:/data` |
| `Address already in use` | Another process on port 8080: `lsof -i :8080` then kill it, or change `-p 9090:8080` |
| `RuntimeError: storage_secret` | Set the `STORAGE_SECRET` environment variable |

### App loads but sessions reset on restart

`STORAGE_SECRET` must be the **same value** across restarts.
If you let it generate randomly, sessions break every time the container restarts.
Store it in a Docker secret or `.env` file and reuse it.

```bash
# .env file (never commit to git)
STORAGE_SECRET=your-stable-32-char-secret-here

docker run --env-file .env ...
# or in compose:
# env_file: .env
```

### Container is unhealthy

```bash
# Check what the health check returns
docker exec cephs3manager \
  python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8080/').status)"
```

If the app hasn't started yet, increase `start-period` in the Dockerfile or
`start_period` in `docker-compose.yml`.

### Slow builds (no cache reuse)

Ensure you `COPY requirements.txt .` and install dependencies **before**
`COPY . .`. This way Docker caches the expensive pip install layer and only
rebuilds it when `requirements.txt` changes — not on every code edit.

```dockerfile
# ✅ Fast (cache-friendly)
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

# ❌ Slow (invalidates pip cache on every code change)
COPY . .
RUN pip install -r requirements.txt
```

The included `Dockerfile` already follows the correct order.

### Check image size

```bash
docker images cephs3manager-web --format "{{.Size}}"
```

Expected: **~300–350 MB** (python:3.13-slim base + NiceGUI + boto3 stack).
If the image is unexpectedly large, check for accidentally copied files:

```bash
# Add a .dockerignore file to exclude these:
.venv/
__pycache__/
*.pyc
.git/
.env
*.db
```

### Recommended `.dockerignore`

Create this file in the project root alongside the `Dockerfile`:

```
.venv
__pycache__
*.pyc
*.pyo
.git
.gitignore
.env
*.db
*.sqlite
.claude
k8s
README.md
DOCKER.md
```

This reduces build context size and prevents secrets/venv from being copied into the image.
