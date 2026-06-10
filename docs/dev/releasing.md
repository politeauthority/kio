# Releasing

## Overview

kio uses a single `VERSION` file at the repo root. Both the API and UI are versioned together and released as a pair. Production images are tagged with the exact version (e.g. `0.1.0`) so any release can be re-deployed or rolled back by name.

```
VERSION file  →  kio-api:0.1.0  +  kio-ui:0.1.0  →  Harbor  →  kustomization.yaml  →  k8s
```

Dev images use a rolling `dev-latest` tag and are not versioned.

---

## Environments

| Environment | UI | API | Image tag |
|---|---|---|---|
| Local dev | `localhost:5174` (Vite) | `localhost:8000` (Docker) | — |
| k8s dev | `kio-dev.example.local` | `api.kio-dev.example.local` | `dev-latest` |
| k8s prod | `kio.example.local` | `api.kio.example.local` | `0.1.0`, `0.2.0`, … |

---

## Versioning

The current version lives in `VERSION` at the repo root.

```bash
task version        # show current version
task bump:patch     # 0.1.0 → 0.1.1  (bug fixes)
task bump:minor     # 0.1.0 → 0.2.0  (new features)
task bump:major     # 0.1.0 → 1.0.0  (breaking changes)
```

Bump before releasing. The release tasks read the version from `VERSION` automatically.

---

## Build numbers

Alongside the semver, kio keeps a monotonic **build number** in a `BUILD` file at the
repo root. It distinguishes repeated builds of the same branch or version — e.g. two
staging builds off `sec`, or a rebuild of `0.1.0` — and lets you identify exactly which
build is running anywhere.

```bash
task version       # show "v{VERSION}+build.{BUILD}", e.g. v0.1.0+build.42
task bump:build    # increment the build number (run automatically by release-*)
```

Every `release-dev` / `release-stg` / `release-prd` runs `bump:build` as its **first
step**, so the API and UI built in one release share the same number. The number shows
up in two places, in two formats (Docker tags can't contain `+`):

| Surface | Format | Example |
|---|---|---|
| `KIO_VERSION` — reported by the live app at `GET /_version` and on the About page | `<base>+build.N` | `0.1.0+build.42` (prod), `sec+build.42` (staging) |
| Immutable image tag in Harbor | `<rolling-tag>-build.N` | `kio-api:0.1.0-build.42`, `kio-api:stg-sec-build.42` |

Each build is pushed under **two tags**: the rolling tag the kustomize overlay points at
(`dev-latest` / `stg-<branch>` / `<semver>`) **and** the immutable `-build.N` tag, so
every build is preserved for rollback and audit while the overlay keeps tracking the
rolling tag.

`release-prd` commits the bumped `BUILD` (via `git-tag`) so production build numbers
persist in git. Staging builds bump the counter locally between releases; because it's a
file counter, the number can drift if you build the same branch from multiple machines.

---

## Releasing to production

### Full release (recommended)

```bash
task bump:patch     # or minor/major — sets the new version
task release-prd    # build → push → stamp → apply → rollout → git tag
git push origin main --tags
```

`release-prd` runs these steps in order:

1. **`bump:build`** — increments the `BUILD` number so this release is uniquely identifiable
2. **`stamp-prd`** — runs `kustomize edit set image` to write the version into `kubernetes-manifests/envs/prd/kustomization.yaml`
3. **`build-prd`** — builds `kio-api`, tagged `{VERSION}` (rolling) and `{VERSION}-build.{BUILD}` (immutable), with `KIO_VERSION={VERSION}+build.{BUILD}`
4. **`push-prd`** — pushes both API tags to Harbor
5. **`build-ui-prd`** — builds `kio-ui`, tagged `{VERSION}` and `{VERSION}-build.{BUILD}`
6. **`push-ui-prd`** — pushes both UI tags to Harbor
7. **`apply-prd`** — `kubectl apply -k kubernetes-manifests/envs/prd/`
8. **`rollout-prd`** — waits for the `kio-api` and `kio-ui` deployments to finish rolling out
9. **`git-tag`** — commits `VERSION` + `BUILD` + `kustomization.yaml` and tags the commit `v{VERSION}`

After the task completes, push the commit and tag:

```bash
git push origin main --tags
```

### Running steps individually

```bash
task build-prd        # build kio-api:{VERSION}
task build-ui-prd     # build kio-ui:{VERSION}
task push-prd         # push API image
task push-ui-prd      # push UI image
task stamp-prd        # write version into envs/prd/kustomization.yaml
task apply-prd        # kubectl apply
task rollout-prd      # wait for rollout
task git-tag          # commit + tag
```

---

## Releasing to dev

Dev releases use a rolling `dev-latest` tag. No version bump needed.

```bash
task release-dev
```

Builds and pushes `kio-api:dev-latest` and `kio-ui:dev-latest`, applies `kubernetes-manifests/envs/dev/`, and rolls out `kio-dev`.

---

## Rollback

Because every prod release is tagged with an exact version in Harbor and recorded in `kustomization.yaml` git history, rolling back is straightforward.

### Roll back to a previous version

```bash
# Edit envs/prd/kustomization.yaml and set newTag to the target version
# Or use kustomize:
cd kubernetes-manifests/envs/prd
kustomize edit set image your-registry.example.com/your-org/kio-api:0.1.0
kustomize edit set image your-registry.example.com/your-org/kio-ui:0.1.0

# Apply and roll out
task apply-prd
task rollout-prd
```

### Roll back using git

```bash
git checkout v0.1.0 -- kubernetes-manifests/envs/prd/kustomization.yaml
task apply-prd
task rollout-prd
```

---

## What gets deployed

The `kustomize build kubernetes-manifests/envs/prd/` output includes:

- `kio-api` Deployment + Service (FastAPI, port 8000)
- `kio-ui` Deployment + Service (nginx, port 80)
- `kio-migrate` Job (Alembic migrations, runs on every apply)
- HTTPRoute `kio.example.local` → `kio-ui:80`
- HTTPRoute `api.kio.example.local` → `kio-api:8000`
- SealedSecret `kio-api` (DATABASE_URL, etc.)
- Per-env patches: CORS_ORIGINS on the API, MQTT_TOPIC_PREFIX on the API

---

## Checking a release

```bash
# Health check
curl http://api.kio.example.local/_health

# Confirm the running image tags
kubectl get deployment kio-api kio-ui -n kio \
  -o jsonpath='{range .items[*]}{.metadata.name}{": "}{.spec.template.spec.containers[0].image}{"\n"}{end}'

# Watch rollout live
kubectl rollout status deployment/kio-api -n kio
kubectl rollout status deployment/kio-ui -n kio
```

---

## Switching a dev kiosk to production

Each kiosk node has two config files stored locally:

```
pi-agent/nodes/kio-2/kiosk.conf.dev   # points at kio-dev.example.local, kio/dev topics
pi-agent/nodes/kio-2/kiosk.conf.prd   # points at kio.example.local, kio/prd topics
```

Both are gitignored (they contain the API token). Switching environments copies the appropriate file to `/etc/kio/kiosk.conf` on the node and restarts the agent.

### First-time prod setup for a node

Before switching a node to prod for the first time, `kiosk.conf.prd` needs a real token. Create one from the production dashboard (`http://kio.example.local`) and fill it in:

```ini
# pi-agent/nodes/kio-2/kiosk.conf.prd
[api]
url = http://kio.example.local
token = kio_...   # token created in the prod dashboard
```

### Deploy agent files and switch to prod

```bash
task kio-2:release-prd
```

Runs in sequence:
1. **`deploy:kio-2`** — copies all `pi-agent/` files (including both `.dev` and `.prd` conf files) to the node, rebuilds the venv
2. **`kio-2:prd`** — copies `kiosk.conf.prd` to `/etc/kio/kiosk.conf` and restarts the agent

To pin to an exact release, run from a clean checkout of the tag:

```bash
git checkout v0.1.0
task kio-2:release-prd
git checkout main
```

### Switch config only (files already deployed)

```bash
task kio-2:prd   # copy kiosk.conf.prd → /etc/kio/kiosk.conf, restart
task kio-2:dev   # copy kiosk.conf.dev → /etc/kio/kiosk.conf, restart
```

These only update the config — they do not re-copy agent files. Use them for quick environment switches after a full deploy has already been done.

### What differs between environments

| | `kiosk.conf.dev` | `kiosk.conf.prd` |
|---|---|---|
| `api.url` | `http://kio-dev.example.local` | `http://kio.example.local` |
| `api.token` | dev dashboard token | prod dashboard token |
| `mqtt.topic_prefix` | `kio/dev` | `kio/prd` |

---

## Harbor images

All images live at `your-registry.example.com/your-org/`. Every build is pushed under a
rolling tag (left) and an immutable `-build.N` tag (right), so the overlay can track the
rolling tag while every individual build stays available for rollback.

| Image | Rolling tag (dev / stg / prod) | Immutable per-build tag |
|---|---|---|
| `kio-api` | `dev-latest` / `stg-<branch>` / `0.1.0` | `dev-build.N` / `stg-<branch>-build.N` / `0.1.0-build.N` |
| `kio-ui` | `dev-latest` / `stg-<branch>` / `0.1.0` | `dev-build.N` / `stg-<branch>-build.N` / `0.1.0-build.N` |
