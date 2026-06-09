# Api UI Development

The dev environment has three components: the FastAPI backend, a Vue frontend, and a PostgreSQL database running in the cluster. The API runs in Docker (or directly on your host); the UI runs via Vite's dev server. Both require a postgres port-forward and an `.env` file.

## Prerequisites

- Docker (for `task dev:api`)
- `kubectl` with cluster access
- `uv` (for `task dev:api:local`)
- Node.js + npm (for the UI)

## 1. Configure environment

Copy `.env.example` to `.env` and fill in the database password:

```bash
cp .env.example .env
```

Get the `kio_dev` postgres password from the cluster:

```bash
kubectl get secret -n q-postgres kio-dev-postgres-user -o jsonpath='{.data.password}' | base64 -d
```

Paste it into `DATABASE_URL` in `.env`. The MQTT values default to the cluster broker and usually don't need changing.

## 2. Forward the database

The cluster postgres is firewalled — you must port-forward it locally before starting the API:

```bash
task port-forward:postgres
```

Leave this running in a dedicated terminal. It forwards `localhost:5432` → `q-postgres` in the cluster.

## 3. Start the API

**Option A — Docker (recommended):** builds and runs the API in a container with hot-reload:

```bash
task dev:api
```

**Option B — directly on host:** runs uvicorn in the `api/` virtualenv, useful for faster iteration or debugger attachment:

```bash
task dev:api:local
```

The API listens on `http://localhost:8000`.

## 4. Start the UI

In a separate terminal:

```bash
task dev:ui
```

Vite starts on `http://localhost:5173` and proxies `/api/*` requests to `localhost:8000`, so the frontend talks to whichever API option you chose above.

## 5. Run migrations

If the schema is behind (after a rebase or first setup):

```bash
cd api
uv run alembic upgrade head
```

## Monitor MQTT traffic

To watch live MQTT messages flowing between the broker and any connected Pi agents:

```bash
task mqtt:monitor
```

## Quick reference

| Task | What it does |
|------|-------------|
| `task port-forward:postgres` | Forward `localhost:5432` → cluster postgres (required) |
| `task dev:api` | Run API in Docker with hot-reload |
| `task dev:api:local` | Run API on host with hot-reload |
| `task dev:ui` | Run Vue frontend dev server on `:5173` |
| `task mqtt:monitor` | Stream all `kio/#` MQTT messages |
