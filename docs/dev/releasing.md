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

The current version lives in `VERSION` at the repo root and is **owned by
[release-please](https://github.com/googleapis/release-please)** — do not edit it by hand
and there are no `bump:*` tasks. The version is derived from Conventional Commit messages
on `main`:

| Commit prefix | Bump | Changelog section |
|---|---|---|
| `fix:`, `perf:`, `deps:`, `refactor:` | patch | yes |
| `feat:` | minor | yes |
| `feat!:` / `BREAKING CHANGE:` footer | major | yes |
| `chore:`, `docs:`, `test:`, `ci:`, `style:` | none | hidden |

release-please keeps these in sync on every release (`release-please-config.json`):
`VERSION`, `src/ha-integration/custom_components/kio/manifest.json` (`version`),
`CHANGELOG.md`, `.release-please-manifest.json`, and the `vX.Y.Z` git tag + GitHub Release.

`src/api/pyproject.toml` and `src/ui/package.json` are deliberately **not** bumped: both
are pinned in lockfiles (`uv sync --frozen` in the image build would fail on a mismatch)
and nothing reads them for the app version — `KIO_VERSION` is stamped at build time.

```bash
task version        # show current version + build number
```

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

Build numbers are a dev/stg concept only — production images carry the clean release-please
semver (`0.6.7`), never a `-build.N` suffix. Staging bumps the counter locally between
releases; because it's a file counter, the number can drift if you build the same branch
from multiple machines.

---

## Releasing to production

### Normal path: merge to `main`

Push to `main`. The `Release Please` workflow (`.github/workflows/release-please.yaml`):

1. **release-pr** — release-please reads the Conventional Commits since the last tag and
   opens/updates a **release PR** (`chore(main): release X.Y.Z`) bumping `VERSION`, the HA
   `manifest.json` and `CHANGELOG.md`; the workflow **auto-merges it** (rebase, `PAT`).
2. That merge is a push to `main`, so the workflow runs again and finds the merged release
   PR still labelled `autorelease: pending`. In order:
   - **build-push** — checks out the PR's merge commit, `task test`, `task ci-build-push`
     (`kio-api:X.Y.Z`, `kio-ui:X.Y.Z`, both also `:latest`).
   - **github-release** — *only now* release-please's release phase tags `vX.Y.Z` and
     publishes the GitHub Release (relabelling the PR `autorelease: tagged`).
   - **deploy** — checks out private-ops, `task stamp-prd` (rewrites `?ref=` and both
     `newTag`s in `kio/kio/kustomization.yaml`), commits `chore(kio): release kio vX.Y.Z`,
     pushes `main`.
3. ArgoCD sees the private-ops commit, runs the `kio-migrate` PreSync hook
   (`alembic upgrade head`) and rolls the Deployments only if it succeeds.

**A version is tagged and released only after its images are in Harbor.** If the build
fails, nothing is tagged; the release PR stays `pending` and the next push to `main` (or a
manual run of the workflow) retries it from the same merge commit — `ci-build-push` skips
image tags that already exist, so a half-pushed release resumes cleanly.

Commits that are not Conventional (`checking in`) never trigger a release.

### Forcing a release

**Actions → Force Release → Run workflow.** Pick `patch`/`minor`/`major` or type an exact
version. It pushes an empty `Release-As: X.Y.Z` commit to `main`, which drives the normal
pipeline above. Use it when only `chore:`/`docs:` commits have landed, or to cut a specific
version number.

### PR checks

`tests.yaml` runs the unit suites on every PR. Add the **`build-check`** label to a PR to
also run `task lint` and a no-push build of both images (`pr-build-check.yaml`).

### Repo settings the pipeline needs (one-time, human)

| Name | Kind | Value |
|---|---|---|
| `HARBOR_USER` | variable | `robot$ci` |
| `CICD_VERSION` | variable | current `polite-cicd` image tag (copy from bookmarx/quigley-api) |
| `HARBOR_PASSWORD` | secret | shared `robot$ci` token (also add to *Dependabot* secrets) |
| `PAT` | secret | classic PAT with `repo` (+`workflow`) scope — must be able to merge PRs and push tags |
| `PRIVATE_OPS_TOKEN` | secret | PAT with contents:write on `politeauthority/private-ops` |

Plus: enable **rebase merging** on the repo, create the `build-check` label, and if `main`
becomes branch-protected the PAT owner must be able to bypass it.

Known failure modes: an **expired PAT** silently stops releases (release PRs open but never
merge) — the auto-merge step logs an explicit 403 hint. Fix the PAT; there is no fallback
by design.

### Escape hatch: re-publish from a laptop

`task release-prd` rebuilds and pushes the images for the **current, already-tagged**
`VERSION` and re-stamps private-ops (e.g. after a registry loss). It refuses to run if
`vVERSION` is not a tag — it never invents versions. Needs `PRIVATE_OPS_DIR` in `.env`
(default `../private-ops`); commit and push private-ops afterwards.

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
