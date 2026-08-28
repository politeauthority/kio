# Releasing

## Overview

kio uses a single `VERSION` file at the repo root. Both the API and UI are versioned together and released as a pair. Production images are tagged with the exact version (e.g. `0.1.0`) so any release can be re-deployed or rolled back by name.

```
VERSION file  →  kio-api:0.1.0  +  kio-ui:0.1.0  →  Harbor  →  private-ops kio/kio/kustomization.yaml  →  ArgoCD  →  k8s
```

**Production is GitOps.** The prod overlay does not live in this repo — it is
`kio/kio/` in the private-ops repo, deployed by ArgoCD. That overlay pulls
`kubernetes-manifests/base/` from here at the release tag (`?ref=vX.Y.Z`) and pins the
image tags to the same version, so a release is "push images + tag, then bump one file
in private-ops". Nothing is ever `kubectl apply`'d to the `kio` namespace by hand.

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

### CI (normal path)

Push to `main`. The `PRD` workflow (`.github/workflows/prd.yaml`) runs the unit tests,
then unless the commit message contains `[skip release]`:

1. `bump:patch` — new `VERSION` (+ HA integration `manifest.json`)
2. `build-prd` / `push-prd` / `build-ui-prd` / `push-ui-prd` — clean `{VERSION}` tags to Harbor
3. commits `release vX.Y.Z [skip release]` and pushes the `vX.Y.Z` tag to this repo
4. checks out private-ops, runs `stamp-prd` (rewrites `?ref=` and both `newTag`s in
   `kio/kio/kustomization.yaml`), commits `chore(kio): release kio vX.Y.Z`, pushes `main`

ArgoCD sees the private-ops commit, runs the `kio-migrate` PreSync hook
(`alembic upgrade head`) and rolls the Deployments only if it succeeds.

Secrets the workflow needs: `HARBOR_PASSWORD`, `PRIVATE_OPS_TOKEN` (PAT with
contents:write on private-ops), optionally `KIO_PUSH_TOKEN` if `main` is protected.

### From a laptop

Needs a private-ops checkout; set `PRIVATE_OPS_DIR` in `.env` (default `../private-ops`).

```bash
task bump:patch     # or minor/major — sets the new version
task release-prd    # build → push → git-tag → stamp private-ops
git push origin main && git push --force origin vX.Y.Z      # tag first: the overlay pins base to it
cd ../private-ops && git add kio/kio/kustomization.yaml \
  && git commit -m "chore(kio): release kio vX.Y.Z" && git push origin main
```

`release-prd` runs these steps in order:

1. **`build-prd`** — builds `kio-api:{VERSION}`
2. **`push-prd`** — pushes it to Harbor
3. **`build-ui-prd`** — builds `kio-ui:{VERSION}`
4. **`push-ui-prd`** — pushes it to Harbor
5. **`git-tag`** — commits `VERSION` + `BUILD` + `manifest.json` and tags the commit `v{VERSION}`
6. **`stamp-prd`** — writes `{VERSION}` into the private-ops overlay: `?ref=v{VERSION}` on the
   remote base and `newTag` for both images

Push **this repo's tag before** pushing private-ops — the overlay references the tag, and
ArgoCD's kustomize build fails until it exists on GitHub.

### Running steps individually

```bash
task build-prd        # build kio-api:{VERSION}
task build-ui-prd     # build kio-ui:{VERSION}
task push-prd         # push API image
task push-ui-prd      # push UI image
task git-tag          # commit + tag
task stamp-prd        # write version into private-ops kio/kio/kustomization.yaml
task rollout-prd      # (optional) restart kio-api and wait — ArgoCD normally does this
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

Every prod release is an immutable tag in Harbor and a `vX.Y.Z` tag here, so rolling back
is a one-file change in private-ops:

```bash
cd ../private-ops
# From kio: writes ?ref= and both newTags for the target version
(cd ../kio && task stamp-prd VERSION=0.1.0)
git add kio/kio/kustomization.yaml
git commit -m "chore(kio): roll back kio to v0.1.0"
git push origin main
```

ArgoCD re-syncs and re-runs `kio-migrate` for that tag. Alembic is a no-op for
revisions already applied, but it will **not** undo a newer migration — if the release
being rolled back added one, run `alembic downgrade <rev>` against the DB first.

---

## What gets deployed

The `kustomize build kio/kio` output (in private-ops) includes:

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
