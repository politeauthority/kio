# Agent Development

The Pi agent (`pi-agent/agent.py`) runs as a systemd service on each kiosk. It reads its config from `/etc/kio/kiosk.conf` at startup and connects to the API and MQTT broker specified there.

Each node has two config files tracked in the repo — one for dev, one for production — so you can deploy the same agent code and flip it between environments without rebuilding anything.

## Config files

Config files live under `pi-agent/nodes/<node-name>/`:

```
pi-agent/nodes/
  kio-1/
    kiosk.conf.dev
  kio-2/
    kiosk.conf.dev
    kiosk.conf.prd
```

The key differences between dev and prod configs:

| Setting | Dev | Prod |
|---------|-----|------|
| `[api] url` | `http://192.168.1.182:8000` (dev k8s service) | `https://api.kio.example.local` |
| `[mqtt] topic_prefix` | `kio/dev` | `kio/prd` |
| `[api] token` | dev token | prod token |

Switching environments is just a matter of copying the right config file to `/etc/kio/kiosk.conf` and restarting the service — the Taskfile commands below handle that.

## Deploying the agent

Deploy copies the `pi-agent/` directory to the Pi and restarts the service. Run this after any code changes:

```bash
task kio-2:deploy   # or kio-1:deploy
```

This SCPs `agent.py`, `VERSION`, node-specific configs, and the browser autostart script, then does `sudo systemctl restart kio-agent`.

## Switching to dev

To point a kiosk at the dev API and MQTT queue:

```bash
task kio-2:dev   # or kio-1:dev
```

This copies `kiosk.conf.dev` → `/etc/kio/kiosk.conf` on the Pi and restarts the agent. The agent will now send heartbeats to the dev API and subscribe to `kio/dev/kiosks/<id>/command`.

## Switching back to production

```bash
task kio-2:prd   # or kio-1:prd
```

Same as above but uses `kiosk.conf.prd`, pointing the agent at the production API and `kio/prd` MQTT topics.

## Deploy and go straight to prod

```bash
task kio-2:release-prd   # or kio-1:release-prd
```

Runs `deploy` then `prd` in sequence — useful when shipping a change directly to production.

## Watching logs

Stream the systemd journal from the agent service in real time:

```bash
task kio-2:logs   # or kio-1:logs
```

## Monitoring MQTT traffic

To see all messages flowing on the broker across both environments:

```bash
task mqtt:monitor
```

This subscribes to `kio/#` so you'll see both `kio/dev` and `kio/prd` traffic.

## Quick reference

| Task | What it does |
|------|-------------|
| `task kio-1:deploy` | Deploy agent to kio-1 and restart service |
| `task kio-2:deploy` | Deploy agent to kio-2 and restart service |
| `task kio-1:dev` | Switch kio-1 to dev API + MQTT |
| `task kio-2:dev` | Switch kio-2 to dev API + MQTT |
| `task kio-1:prd` | Switch kio-1 to prod API + MQTT |
| `task kio-2:prd` | Switch kio-2 to prod API + MQTT |
| `task kio-1:release-prd` | Deploy kio-1 and switch to prod |
| `task kio-2:release-prd` | Deploy kio-2 and switch to prod |
| `task kio-1:logs` | Stream agent logs from kio-1 |
| `task kio-2:logs` | Stream agent logs from kio-2 |
| `task mqtt:monitor` | Watch all `kio/#` MQTT traffic |
