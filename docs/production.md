# Production Deployment

## Architecture

```
kio.example.local          →  kio-ui (nginx, Vue SPA)     [prod]
api.kio.example.local      →  kio-api (FastAPI)            [prod]

kio-dev.example.local      →  kio-ui (nginx, Vue SPA)     [dev]
api.kio-dev.example.local  →  kio-api (FastAPI)            [dev]

All routes go through the nginx-gateway-fabric-private Gateway (internal only).
```

### Kubernetes namespaces

| Namespace | Purpose |
|---|---|
| `kio` | Production UI + API |
| `kio-dev` | Dev/staging UI + API |
| `mosquitto` | Shared MQTT broker (all envs) |
| `q-postgres` | Shared PostgreSQL (all envs) |

### MQTT topic namespacing

Dev and prod share the same mosquitto broker (`192.168.1.100:1883` / `mosquitto-mqtts.mosquitto.svc.cluster.local:1883`). Topics are prefixed per environment to avoid conflicts:

| Environment | Prefix | Example topic |
|---|---|---|
| Local dev / k8s dev | `kio/dev` | `kio/dev/kiosks/{id}/command` |
| k8s prod | `kio/prd` | `kio/prd/kiosks/{id}/command` |

The prefix is set via `MQTT_TOPIC_PREFIX` env var in the API and `topic_prefix` in `/etc/kio/kiosk.conf` on each node. They must match for commands to reach the right node.

---

## Releasing

See [releasing.md](releasing.md) for the full release process, versioning, and rollback procedures.

---

## Database migrations

Migrations run via Alembic. Always run against the **read-write** postgres endpoint.

```bash
# Port-forward if outside the cluster
task port-forward:postgres

# Run migrations
cd api && .venv/bin/alembic upgrade head
```

For k8s, the `migrate-job.yaml` in base/api runs migrations as a Job before the deployment rolls out.

---

## Node management

### Provisioning a new node

1. Create the kiosk in the dashboard → copy the UUID
2. Create a node token for it → copy `kio_...`
3. Copy `pi-agent/kio.conf.example` → `kio.conf`, fill in all fields
4. Run the provisioner:

```bash
bash pi-agent/setup.sh kio.conf
```

The script SSHes to the Pi, installs the agent to `/opt/kio-agent/`, writes `/etc/kio/kiosk.conf`, and enables the systemd service.

### Deploying to kio-2 (dev path)

kio-2 runs the agent from `~/kio/pi-agent/` via labwc autostart rather than systemd. Use the deploy task:

```bash
task deploy:kio-2
```

This copies all pi-agent files, sets up the venv, writes `/etc/kio/kiosk.conf` from `nodes/kio-2/kiosk.conf`, and restarts the agent.

### Switching kio-2 between environments

```bash
task kio-2:dev   # → http://kio-dev.example.local, topic prefix kio/dev
task kio-2:prd   # → http://kio.example.local,     topic prefix kio/prd
```

These update `/etc/kio/kiosk.conf` on the Pi via SSH and restart the agent. The node will check in to the new environment within 30 seconds.

---

## Node config reference (`/etc/kio/kiosk.conf`)

```ini
[kiosk]
id = <uuid from dashboard>
features = display_power,cec,input_switch   # comma-separated, optional

[api]
url = http://kio.example.local
token = kio_...                             # node token from dashboard

[mqtt]
host = 192.168.1.100
port = 1883
topic_prefix = kio/prd                      # must match API environment
```

---

## Monitoring

```bash
# Watch all kio MQTT traffic
task mqtt:monitor

# Agent logs on kio-2
ssh kio-2 "tail -f ~/kio/logs/kio-agent.log"

# API health
curl http://kio-dev.example.local/_health
curl http://kio.example.local/_health
```

---

## Secrets

API secrets are stored as SealedSecrets in `kubernetes-manifests/envs/{env}/secrets/sealed-api-secrets.yaml`. The secret must contain:

- `DATABASE_URL` — postgres connection string
- `CORS_ORIGINS` — JSON list of allowed frontend origins (e.g. `["http://kio.example.local"]`)

Node tokens are created per-kiosk through the dashboard and stored only in `/etc/kio/kiosk.conf` on each node.
