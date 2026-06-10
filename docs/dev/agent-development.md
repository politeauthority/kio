# Agent Development

The Pi agent (`src/pi-agent/agent.py`) runs as a systemd service on each kiosk. It reads its config from `/etc/kio/kiosk.yaml` at startup and connects to the API and MQTT broker specified there.

Each node has per-environment config files tracked in the repo — one for dev, one for production — so you can deploy the same agent code and flip it between environments without rebuilding anything.

## Config files

Config files live under `configs/agents/`, named `<node>-kiosk.<env>.yaml`:

```
configs/agents/
  example-config.yaml        # template
  kio-2-kiosk.dev.yaml
  kio-2-kiosk.prd.yaml
  kio-3-kiosk.dev.yaml
  kio-3-kiosk.prd.yaml
```

They are YAML. A dev config looks like:

```yaml
api:
  url: http://192.168.50.182:8000   # dev k8s API service
  token: kio_...                    # dev node token
  # tls_verify: optional — true (default) | <ca-bundle path> | false

mqtt:
  host: 192.168.50.86
  port: 1883
  topic_prefix: kio/dev             # prod uses kio/prd
```

The key differences between dev and prod are `api.url`, `api.token`, and `mqtt.topic_prefix` (`kio/dev` vs `kio/prd`). Switching environments copies the right config file to `/etc/kio/kiosk.yaml` and restarts the service — the Taskfile commands below handle that. (See "API TLS verification" for `tls_verify`.)

## Deploying the agent

Deploy copies the local `src/pi-agent/` tree to the Pi and re-runs `setup.sh` (which reinstalls the agent, repairs ownership, and restarts the service). The node's existing config is kept. Run this after any code changes:

```bash
task kio-2:deploy   # or kio-3:deploy
```

Under the hood (the shared `_kio:install` task) this SCPs `src/pi-agent/.` and `VERSION` to `/tmp/kio-deploy` on the node, then runs `sudo bash /tmp/kio-deploy/setup.sh --local` — `--local` so it installs only from the copied source and never pulls from git.

## Installing on a fresh Pi (`setup.sh`)

`setup.sh` is the idempotent installer: it installs packages, writes `/etc/kio/kiosk.yaml`, installs the agent to `/opt/kio-agent/`, and enables the systemd service. Useful flags:

| Flag | Purpose |
|------|---------|
| `--api-url <url>` | API base URL (required on first install) |
| `--token <kio_…>` | Node token from the dashboard |
| `--env dev\|prd` | Select the stored per-env config on re-install |
| `--config <file>` | Read everything from a kiosk YAML — no prompts, no API fetch |
| `--local` | Run only from the copied source; never pull from git |
| `--ca-cert <file>` | Install a CA into the system trust store before first contact |
| `--accept-cert` | Trust-on-first-use: fetch + pin the API's cert (see below) |
| `--insecure-tls` | Skip API TLS verification (testing only) |
| `--allow-http` | Acknowledge an unencrypted `http://` API (interactive runs are prompted instead) |
| `--dns <ip[,ip]>` | Set the node's DNS server(s) — e.g. a Pi-hole that resolves internal names (see below) |

> `setup.sh` only targets Raspberry Pi OS (Raspbian-type) on a Raspberry Pi — it checks for `apt` + Pi markers (`/etc/rpi-issue`, `/proc/device-tree/model`) up front and exits early on anything else, before the git bootstrap.

### Running from manually-copied source (`--local`)

When `agent.py` sits beside `setup.sh`, the git self-bootstrap is skipped automatically. `--local` makes that explicit — it never touches git and errors loudly (instead of silently cloning) if the source isn't there:

```bash
scp -r src/pi-agent/. <pi>:/tmp/kio-deploy
scp VERSION <pi>:/tmp/kio-deploy/VERSION
ssh -t <pi> "sudo bash /tmp/kio-deploy/setup.sh --local --api-url https://… --token kio_…"
```

The `task <node>:deploy` flow (via the shared `_kio:install` task) already passes `--local`.

## API TLS verification

The agent verifies the API's TLS cert on every call (heartbeat, config, settings, cert sync, command acks). The `tls_verify` value under `api:` in `/etc/kio/kiosk.yaml` controls how; `resolve_tls_verify()` in `agent.py` maps it onto requests' `verify=`:

| `tls_verify` | Behaviour |
|--------------|-----------|
| `true` (default) | Verify against the **system trust store** (`/etc/ssl/certs/ca-certificates.crt`) if present, else certifi |
| `<path>` | Verify against that CA bundle (explicit pin) |
| `false` | No verification (insecure; logs a warning at startup) |

**Why the system store and not certifi:** Python `requests` uses its bundled certifi list by default, which never sees `update-ca-certificates` additions. Defaulting "verify on" to the system store means it covers public CAs *and* any internal CA the node has been told to trust (including whatever `sync_certs` installs) — without having to disable verification.

### Choosing the option per deployment

| API cert | Setup flag | Result |
|----------|-----------|--------|
| Publicly-trusted (Let's Encrypt, etc.) | *(none)* | Trusted out of the box |
| Internal CA, file on hand | `--ca-cert ca.crt` | Installed into the system store before first contact |
| Private/self-signed, no CA file | `--accept-cert` | Fetched + pinned on first contact (TOFU) |
| Plain HTTP / just testing | `--insecure-tls` | Verification off |

### Trust-on-first-use (`--accept-cert`)

For a private cert with no CA file at hand, `--accept-cert`:

1. Fetches the API's cert chain via `openssl s_client` — this first reach is unverified (the TOFU tradeoff).
2. Pins it to `/etc/kio/api-pinned.crt` and prints the leaf SHA-256 fingerprint — **verify it out-of-band**.
3. Writes `tls_verify: /etc/kio/api-pinned.crt`, so the rest of setup and every later agent call verify against the pinned cert.

The pinned cert lives **outside** `/etc/kio/certs/` deliberately — `sync_certs` wipes that directory on every sync.

### The bootstrap constraint

Verifying the API's cert requires already holding its trust anchor, so the anchor has to arrive out-of-band: `--ca-cert`, `--accept-cert`, a pre-trusted public CA, or baked into the image. **`sync_certs` (`/agent/certs`) can never bootstrap agent→API trust** — fetching it already needs a trusted connection. It only *extends* trust (display-site CAs, rotations) after trust exists.

If first contact fails because the cert isn't trusted, `setup.sh` detects the TLS error (curl exit 35/51/58/60/66/77/83) and points you at `--ca-cert` / `--accept-cert` / `--insecure-tls` instead of reporting a phantom outage.

## Resolving internal hostnames (custom DNS)

If the API uses an internal hostname like `api.stg.kio.colfax.int`, the Pi needs something that can resolve it — those names aren't in public DNS. Two mechanisms:

- **`extra_hosts` sync** — the API serves host entries (global + per-kiosk) that the agent writes into `/etc/hosts` via `update-hosts` on each `sync_hosts`. Good for a handful of names, but it **can't** resolve the API's *own* hostname on first contact (the agent has to reach the API to fetch them) — the same bootstrap shape as the TLS trust anchor.
- **A real DNS server** (e.g. a Pi-hole) via `--dns`, set *before* first contact so the API hostname resolves:

  ```bash
  sudo bash setup.sh --dns 192.168.50.2 --api-url https://api.stg.kio.colfax.int --token kio_…
  ```

  Comma/space-separate multiple servers; `KIO_DNS` works for automation; interactive runs are prompted (blank keeps the current DNS).

**How it persists.** `apply_dns` writes to whichever network stack is active. On NetworkManager (Raspberry Pi OS) the durable part is a global-DNS drop-in at `/etc/NetworkManager/conf.d/90-kio-dns.conf` — netplan never regenerates `conf.d`, so it survives reboots even though NM's connection profiles are rebuilt from netplan into `/run` on every boot — plus per-connection `ipv4.dns` as a fallback. It applies via `nmcli general reload` (no link bounce, so it won't drop an SSH-over-Wi-Fi session). Other stacks: systemd-resolved (`/etc/systemd/resolved.conf.d/`), dhcpcd (`/etc/dhcpcd.conf`), else a direct `/etc/resolv.conf` write.

## Switching to dev

To point a kiosk at the dev API and MQTT queue:

```bash
task kio-2:dev   # or kio-3:dev
```

This copies `configs/agents/<node>-kiosk.dev.yaml` → `/etc/kio/kiosk.yaml` on the Pi and restarts the agent. (`kio-2:dev` also re-syncs the agent code; `kio-3:dev` pushes config only.) The agent will now send heartbeats to the dev API and subscribe to `kio/dev/kiosks/<id>/command`.

## Switching back to production

```bash
task kio-2:prd   # or kio-3:prd
```

Same as above but uses `<node>-kiosk.prd.yaml`, pointing the agent at the production API and `kio/prd` MQTT topics.

## Deploy and go straight to dev/prod

```bash
task kio-2:release-dev   # deploy + switch to dev
task kio-2:release-prd   # deploy + switch to prod
```

Runs `deploy` then `dev`/`prd` in sequence — useful when shipping a change directly to a running environment.

## First-time setup of a node

```bash
task kio-3:setup
```

Runs the full install against a node that has the source available, using its dev config. For a brand-new Pi, see [Onboarding a New Kiosk](../features/onboarding-a-kiosk.md).

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

Tasks exist per node (`kio-1`, `kio-2`, `kio-3`); `<node>` below stands in for any of them.

| Task | What it does |
|------|-------------|
| `task <node>:setup` | First-time install on the node, using its dev config |
| `task <node>:deploy` | Copy local source + re-run `setup.sh --local`, keep config, restart |
| `task <node>:dev` | Switch node to dev API + MQTT |
| `task <node>:prd` | Switch node to prod API + MQTT |
| `task <node>:release-dev` | Deploy and switch to dev |
| `task <node>:release-prd` | Deploy and switch to prod |
| `task <node>:logs` | Stream agent logs from the node |
| `task mqtt:monitor` | Watch all `kio/#` MQTT traffic |
