# CephS3Manager-Web

A modern, self-hosted S3 + Ceph RGW administration tool built with Python and NiceGUI.
Manage buckets, objects, users, and cluster quotas from a clean GitHub-dark UI.

---

## Features

| Feature | Description |
|---------|-------------|
| **Multi-connection** | Store and switch between multiple S3 / Ceph RGW endpoints |
| **Bucket management** | Create, delete, browse — with Policy / CORS / Versioning / Lifecycle / Permissions editor |
| **Object explorer** | AG Grid table with client-side pagination, live quick-filter, virtual scrolling, bulk selection, inline per-row actions (preview, download, copy, rename, presign URL, delete), cross-bucket copy, folder navigation with breadcrumb + tree |
| **User management** | Full Ceph RGW Admin Ops: create/delete/suspend users, manage S3 keys, quotas, bucket ownership |
| **Settings** | Per-session: page size, presign expiry, multipart thresholds, theme |
| **Dark / Light mode** | Persisted per browser session; AG Grid themed via injected CSS for full dark-mode support |
| **Keyboard shortcuts** | `U` upload · `N` new folder · `R` refresh · `Escape` close dialog (Objects page) |

---

## Quick Start (Docker Compose)

```bash
git clone <this-repo>
cd s3mangerkuber

# Edit the secret before running in production
docker compose up -d

# Open browser
open http://localhost:8080
```

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATA_DIR` | `/data` | SQLite database directory |
| `APP_HOST` | `0.0.0.0` | Bind address |
| `APP_PORT` | `8080` | HTTP port |
| `STORAGE_SECRET` | — | **Required.** NiceGUI session cookie secret (32+ chars) |
| `DEV_RELOAD` | `false` | Enable hot-reload (development only) |

---

## Docker Build

```bash
# Build
docker build -t cephs3manager-web:latest .

# Run
docker run -d \
  -p 8080:8080 \
  -v cephs3mgr_data:/data \
  -e STORAGE_SECRET="$(openssl rand -hex 32)" \
  --name cephs3manager \
  cephs3manager-web:latest
```

The image uses a **two-stage build** (`python:3.13-slim`) and runs as a non-root user (`appuser`).

---

## Kubernetes Deployment

### Prerequisites

- Kubernetes 1.24+
- A StorageClass for the PVC (SQLite database)
- An Ingress controller (nginx recommended)

### 1 – Generate a storage secret

```bash
kubectl create secret generic cephs3manager-secret \
  --namespace default \
  --from-literal=storage-secret="$(openssl rand -hex 32)"
```

Or edit `k8s/deployment.yaml` and replace the placeholder in the `Secret` block.

### 2 – Apply all manifests

```bash
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/deployment.yaml   # includes Deployment, PVC, Secret
kubectl apply -f k8s/service.yaml      # includes Service + Ingress
```

### 3 – Check rollout

```bash
kubectl rollout status deployment/cephs3manager
kubectl logs -f deployment/cephs3manager
```

### StorageClass

The PVC in `k8s/deployment.yaml` uses `storageClassName: standard`.
Change this to match your cluster:

| Cluster type | StorageClass |
|--------------|--------------|
| Rook-Ceph block | `rook-ceph-block` |
| AWS EKS | `gp2` / `gp3` |
| GKE | `standard-rwo` |
| k3s local-path | `local-path` |
| Kind (dev) | `standard` |

### Ingress + TLS

Edit `k8s/service.yaml` and set your hostname:

```yaml
rules:
  - host: s3manager.example.com
```

To enable TLS with cert-manager:

```yaml
metadata:
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  tls:
    - hosts:
        - s3manager.example.com
      secretName: cephs3manager-tls
  rules:
    - host: s3manager.example.com
      ...
```

---

## Connecting to Rook-Ceph RGW

When running **inside the same Kubernetes cluster** as Rook-Ceph, use the internal Service DNS:

```
http://rook-ceph-rgw-<zone-name>.rook-ceph.svc.cluster.local
```

Find your RGW service name:

```bash
kubectl get svc -n rook-ceph | grep rgw
# Example output:
# rook-ceph-rgw-my-store   ClusterIP  10.96.x.x  <none>  80/TCP
```

Connection settings in the UI:

| Field | Value |
|-------|-------|
| Endpoint | `http://rook-ceph-rgw-my-store.rook-ceph.svc.cluster.local` |
| Access Key | From `kubectl get secret ...` (see below) |
| Secret Key | From `kubectl get secret ...` |
| Region | `us-east-1` (or whatever your zone uses) |
| Path-style | **Enabled** (required for Ceph) |

---

### Creating a Rook-Ceph admin user via CRD

The recommended way to create an RGW user in Rook is with a `CephObjectStoreUser` Custom Resource.
Rook automatically generates S3 credentials and stores them in a Kubernetes Secret.

#### 1 — Apply the CephObjectStoreUser manifest

```yaml
# k8s/ceph-rgw-admin-user.yaml
apiVersion: ceph.rook.io/v1
kind: CephObjectStoreUser
metadata:
  name: s3manager-admin          # arbitrary name for the CRD object
  namespace: rook-ceph
spec:
  store: my-store                # must match your CephObjectStore .metadata.name
  displayName: "S3Manager Admin"
  capabilities:
    user: "*"
    bucket: "*"
    metadata: "*"
    usage: "*"
    zone: "*"
```

```bash
kubectl apply -f k8s/ceph-rgw-admin-user.yaml

# Wait until Ready
kubectl -n rook-ceph get cephobjectstoreuser s3manager-admin
# NAME               PHASE
# s3manager-admin    Ready
```

> The `capabilities` block grants full Admin Ops access (`users=*;buckets=*;...`).
> Without it the user can do S3 operations but **cannot** use the Users/Admin tab in CephS3Manager.

#### 2 — Retrieve the auto-generated credentials

Rook creates a Secret named `rook-ceph-object-user-<store>-<user>`:

```bash
# Access Key
kubectl -n rook-ceph get secret \
  rook-ceph-object-user-my-store-s3manager-admin \
  -o jsonpath='{.data.AccessKey}' | base64 -d

# Secret Key
kubectl -n rook-ceph get secret \
  rook-ceph-object-user-my-store-s3manager-admin \
  -o jsonpath='{.data.SecretKey}' | base64 -d
```

Or in one command suitable for `.env` / ConfigMap:

```bash
kubectl -n rook-ceph get secret \
  rook-ceph-object-user-my-store-s3manager-admin \
  -o go-template='ACCESS_KEY={{.data.AccessKey | base64decode}}
SECRET_KEY={{.data.SecretKey | base64decode}}'
```

#### 3 — Verify admin caps (optional)

If you need to check or add caps manually (e.g. on an existing user):

```bash
# Exec into the Rook toolbox pod
kubectl -n rook-ceph exec -it deploy/rook-ceph-tools -- bash

# Inside toolbox:
radosgw-admin user info --uid=s3manager-admin | grep caps -A 20

# Add caps if missing:
radosgw-admin caps add --uid=s3manager-admin \
  --caps="users=*;buckets=*;metadata=*;usage=*;zone=*"
```

#### 4 — Configure the connection in CephS3Manager

| Field | Value |
|-------|-------|
| **Endpoint** | `http://rook-ceph-rgw-my-store.rook-ceph.svc.cluster.local` |
| **Access Key** | Output of step 2 |
| **Secret Key** | Output of step 2 |
| **Region** | `us-east-1` (Rook default; check your `CephObjectStore`) |
| **Verify SSL** | Off for plain HTTP, On for HTTPS with valid cert |
| **Public Endpoint** | External URL if presigned URLs must be reachable outside the cluster (e.g. `https://s3.company.com`) |
| **Admin Endpoint** | Same as Endpoint — Rook exposes the Admin Ops API on the same port (`/admin/*`) |

> **Enable Admin Mode** toggle in the connection dialog to activate the Users/Admin tab.

---

### Realm / Zone considerations

Rook creates a default **realm → zone group → zone** hierarchy automatically when you deploy a `CephObjectStore`.
No manual realm configuration is needed unless you run **multi-site** replication.

If you have a custom realm and your users are in a specific zone group, make sure
`CephObjectStoreUser.spec.store` matches the `CephObjectStore` name tied to that zone.
The Admin Ops API endpoint is always the RGW Service URL of that store.

```bash
# List realms / zone groups / zones (inside toolbox):
radosgw-admin realm list
radosgw-admin zonegroup list
radosgw-admin zone list
```

---

## Ceph Admin API (RGW Admin Ops)

The **Users** tab in CephS3Manager uses the Ceph RGW Admin Ops API
(`/admin/user`, `/admin/bucket`, `/admin/usage`, etc.)
authenticated with **SigV4** using your admin credentials.

### Requirements

1. The RGW user must have **admin caps**:

   ```bash
   radosgw-admin caps add --uid=admin \
     --caps="users=*;buckets=*;metadata=*;usage=*;zone=*"
   ```

2. Enable **Admin API access** — in `ceph.conf` or Rook CephObjectStore:

   ```ini
   [client.rgw.my-store]
   rgw_enable_apis = s3, admin
   ```

   For Rook, add to `CephObjectStore` spec:
   ```yaml
   gateway:
     additionalConfig:
       rgw_enable_apis: "s3, admin"
   ```

3. The Admin API endpoint is the **same URL** as the S3 endpoint — just enable **Admin Mode** in the connection dialog.

### Security note

The Admin API should **not** be exposed to the public internet.
Use it only via internal cluster DNS or a VPN / bastion.
If you must expose it, put it behind an Ingress with authentication middleware
(e.g., `nginx.ingress.kubernetes.io/auth-url`).

---

## Architecture

```
┌─────────────────────────────────────────┐
│            Browser (WebSocket)          │
└────────────────┬────────────────────────┘
                 │ ASGI / WebSocket
┌────────────────▼────────────────────────┐
│         CephS3Manager-Web               │
│  NiceGUI + FastAPI + Uvicorn            │
│                                         │
│  ┌─────────┐  ┌──────────┐  ┌────────┐ │
│  │ s3_client│  │rgw_admin │  │ SQLite │ │
│  │  (boto3) │  │(SigV4)   │  │  (DB)  │ │
│  └────┬─────┘  └────┬─────┘  └────────┘ │
└───────┼─────────────┼────────────────────┘
        │             │
┌───────▼─────────────▼────────────────────┐
│         Ceph RGW (Rook / standalone)      │
│   S3 API  (:80)   Admin API (/admin/*)    │
└──────────────────────────────────────────┘
```

---

## Keyboard Shortcuts (Objects page)

| Key | Action |
|-----|--------|
| `U` | Open upload dialog |
| `N` | New folder |
| `R` | Refresh current object list |
| `Escape` | Close any open dialog |

## Object Browser — AG Grid

The Objects page uses **AG Grid Community** (via NiceGUI `ui.aggrid`) for its file listing:

- **Client-side pagination** — 25 / 50 / 100 / 250 rows per page (selector in footer)
- **Live quick-filter** — type in the search box; filters by name instantly, no server round-trip
- **Bulk selection** — checkbox column; "Delete selected" toolbar button with confirmation dialog
- **Inline action icons** per row — Preview 👁 · Download ⬇ · Copy 📋 · Rename ✏ · Presigned URL 🔗 · Delete 🗑
- **Folder navigation** — click folder row or `..` row to navigate; breadcrumb + left-panel tree stay in sync
- **Dark-mode theming** — CSS injected via `ui.add_head_html()` targeting `.ag-theme-balham` classes (CSS custom properties are not reliable in the bundled AG Grid version)

---

## Development

```bash
# Install deps
pip install -r requirements.txt

# Run with hot-reload
DEV_RELOAD=true STORAGE_SECRET=dev-secret python main.py
```

Logs are written to stdout in `[LEVEL] module: message` format.
Set `LOG_LEVEL=DEBUG` for verbose output:

```bash
LOG_LEVEL=DEBUG python main.py
```

---

## License

MIT
