# CI/CD

How kio is built, packaged, and deployed today.

> **There is no hosted CI runner.** kio has no GitHub Actions / GitLab CI / Jenkins
> pipeline. Every build and deploy is driven from a developer machine through
> [`task`](https://taskfile.dev) targets defined in the repo-root `Taskfile.yaml`,
> talking directly to the Harbor registry and the Kubernetes cluster (`kubectl` +
> `kustomize` + `kubeseal`). This document describes that flow end to end.

Related docs: [releasing.md](releasing.md) (prod/dev release mechanics & rollback),
[staging.md](staging.md) (per-branch staging), [testing.md](testing.md) (unit + e2e tests).

---

## The pipeline

The same five logical stages run for every environment; only the image tag and a
few build flags differ.

```
 VERSION / branch                Harbor registry            Kubernetes (kustomize overlay)
┌────────────────┐   build   ┌──────────────────┐  stamp  ┌───────────────────────────────┐
│ kio-api source │ ────────▶ │ kio-api:<tag>    │ ──────▶ │ envs/<env>/kustomization.yaml │
│ kio-ui  source │           │ kio-ui:<tag>     │  push   │   images: newTag: <tag>       │
└────────────────┘           └──────────────────┘         └───────────────────────────────┘
                                                                         │ apply
                                                                         ▼
                                                       ┌───────────────────────────────────┐
                                                       │ kio-migrate Job  (alembic upgrade) │
                                                       │ kio-api Deployment (uvicorn :8000) │
                                                       │ kio-ui  Deployment (nginx  :8080)  │
                                                       └───────────────────────────────────┘
                                                                         │ rollout status
                                                                         ▼  (wait, maxUnavailable=0)
```

1. **Bump** — `bump:build` increments the `BUILD` number so the release is uniquely
   identifiable (see [Versioning & build numbers](#versioning--build-numbers)).
2. **Build** — `docker buildx build --platform linux/amd64` against the repo root
   using `docker/Dockerfile.api` / `docker/Dockerfile.ui`. Each image is tagged twice:
   a rolling tag and an immutable `-build.N` tag.
3. **Push** — `docker push` of both tags to Harbor (`$HARBOR/kio-api`, `$HARBOR/kio-ui`).
4. **Stamp** — `kustomize edit set image` writes the rolling tag into the env's
   `kustomization.yaml` (prod/stg only; dev uses a fixed rolling tag).
5. **Apply** — `kubectl apply -k kubernetes-manifests/envs/<env>/`. This applies the
   Deployments, Services, HTTPRoutes, SealedSecret, and the `kio-migrate` Job.
6. **Rollout** — `kubectl rollout restart` + `rollout status` until both
   Deployments report ready.

`$HARBOR` is read from `.env` (`HARBOR=...`); see `.env.example`. All `buildx`
builds target `linux/amd64` because the cluster is amd64 while developer machines
are often arm64 (Apple Silicon).

---

## Environments

| Env | Namespace | Image tag | API build target | Tests in image? |
|-----|-----------|-----------|------------------|-----------------|
| **dev** | `kio-dev` | `dev-latest` (rolling) | `production` | no |
| **staging** | `kio-stg` | `stg-<branch>` | **`test`** | **yes** |
| **production** | `kio` | `<VERSION>` (e.g. `0.4.1`) | `production` | no |

The image tag is the single knob that selects what a namespace runs. `kustomize`'s
`images:` transformer rewrites the tag on **every** resource that references the
image — the `kio-api` Deployment *and* the `kio-migrate` Job — so a deploy moves the
app and its migrations together.

---

## Versioning & build numbers

Two coordinates identify any artifact: the **semver** (`VERSION` file) and a monotonic
**build number** (`BUILD` file). The build number distinguishes repeated builds of the
same branch or version — every `release-*` runs `bump:build` first, so the API and UI in
one release share the number. It surfaces in two formats (Docker tags can't contain `+`):

- `KIO_VERSION` — `<base>+build.N`, reported live by the app at `GET /_version` and on
  the About page. E.g. `0.4.1+build.42` (prod), `sec+build.42` (staging).
- Immutable image tag — `<rolling-tag>-build.N`, e.g. `kio-api:stg-sec-build.42`.

Every build is pushed under **both** the rolling tag the overlay tracks (`dev-latest` /
`stg-<branch>` / `<semver>`) and the immutable `-build.N` tag, so each build is preserved
in Harbor for rollback/audit while the overlay keeps pointing at the rolling tag. To
identify what's running anywhere: `kubectl exec -n <ns> deploy/kio-api -- \
python -c "import urllib.request,json;print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/_version')))"`.

`release-prd` commits the bumped `BUILD` (via `git-tag`) so prod build numbers persist;
staging bumps it locally between releases. As a file counter it can drift if the same
branch is built from multiple machines. See [releasing.md](releasing.md#build-numbers).

---

## Image targets: production vs. test

Both Dockerfiles are multi-stage (see [the Dockerfiles](../../docker/) for the full
build). The API Dockerfile exposes two final targets:

| Target | Contents | Size (approx) | Used by |
|--------|----------|---------------|---------|
| `production` | venv (runtime deps only, from `uv.lock`) + `app/` + Alembic. Non-root `app` (uid 1000). No uv, no dev tooling, no tests. | ~245 MB | dev, prod |
| `test` | everything in `production` **plus** the dev dependency group (pytest, ruff, black) and `tests/`. | ~315 MB | **staging** |

Both run as the same non-root uid and share the same runtime layer, so the staging
image is byte-for-byte identical to production *plus* the test additions — what you
test in staging is what ships.

The UI image has a single runtime target (`nginxinc/nginx-unprivileged`, rootless on
:8080); there are no UI unit tests, so staging and prod use the same UI image (staging
just bakes in the `KIO_BRANCH` banner).

### Why staging carries the tests

The staging image is built with `--target test`, so the deployed pod ships pytest and
the full unit-test suite. The Kubernetes Deployment overrides the container command to
run uvicorn, so the image's default `CMD ["pytest", "-q"]` is ignored in normal
operation — but you can run the suite **inside the running staging pod**:

```bash
kubectl exec -n kio-stg deploy/kio-api -- pytest -q
```

This validates the exact artifact that's deployed (same Python, same pinned deps),
against the mocked dependencies the unit tests use. Live end-to-end tests are separate
— run them from your machine against the staging URLs (see below and
[testing.md](testing.md)).

Production and dev images are built with `--target production`: smaller surface, no
pytest, no dev tooling, no test code.

---

## Deploying

### Staging (per branch)

```bash
task release-stg BRANCH=feat/my-feature
```

Runs in order: `build-stg` (**`--target test`**) → `push-stg` → `build-ui-stg`
(branch banner) → `push-ui-stg` → `stamp-stg` → `apply-stg` → `rollout-stg`. Images
are tagged `stg-<branch>` (slashes become dashes). Full details in
[staging.md](staging.md).

Run the deployed image's unit tests, then live e2e tests:

```bash
kubectl exec -n kio-stg deploy/kio-api -- pytest -q          # in-cluster unit tests
KIO_API_URL=http://api.stg.kio.example.local \
KIO_UI_URL=http://stg.kio.example.local \
task test:e2e                                                 # live e2e from your machine
```

### Production (versioned)

```bash
task bump:patch       # or minor / major — updates VERSION
task release-prd      # build → push → stamp → apply → rollout → git tag
git push origin main --tags
```

`release-prd` builds both images with `--target production` and tags them with the
exact `VERSION`. Every prod release is an immutable, named tag in Harbor and a commit
in git history, so rollback is "set the tag back and re-apply." Full details and
rollback steps in [releasing.md](releasing.md).

### Dev (rolling)

```bash
task release-dev      # build production images tagged dev-latest, push, apply, rollout
```

No version bump; `dev-latest` is overwritten each time.

---

## Database migrations

Migrations are **not** run by hand. `kubernetes-manifests/base/api/migrate-job.yaml`
defines `kio-migrate`, a Job that runs `alembic upgrade head` using the same image tag
as the API Deployment. Because it's part of the base kustomization, every
`task apply-<env>` re-applies it and it runs on each deploy (`ttlSecondsAfterFinished:
300` cleans it up).

`alembic` is on `PATH` in **both** image targets (it's a runtime dependency in the
venv), so migrations run identically whether the image is `production` or `test`.

To run migrations manually against the dev compose stack:

```bash
task db:migrate       # docker compose exec api ... alembic upgrade head
```

---

## Container hardening (what gets deployed)

Both images and the k8s manifests are hardened to run unprivileged:

- **API** — non-root `app` (uid 1000), runtime deps pinned via `uv.lock`, no build
  tooling in the final image. Pod runs `runAsNonRoot` + `readOnlyRootFilesystem`
  (with a `/tmp` emptyDir) + `drop: [ALL]` capabilities + `seccompProfile:
  RuntimeDefault`. The same applies to the `kio-migrate` Job.
- **UI** — `nginxinc/nginx-unprivileged`: master and workers run as uid 101, listen
  on `:8080` (no privileged-port bind). Pod runs `runAsNonRoot` + `drop: [ALL]` +
  `seccompProfile: RuntimeDefault`. `readOnlyRootFilesystem` is intentionally *not*
  set because the entrypoint rewrites runtime config into `index.html` on start.
- **Build context** — a repo-root `.dockerignore` keeps secrets (`.env*`), VCS data,
  `node_modules`, and unrelated components out of the build context and image layers.

---

## Secrets

Database credentials are delivered as Bitnami **SealedSecrets**, one per environment,
committed at `kubernetes-manifests/envs/<env>/secrets/sealed-api-secrets.yaml`. Each is
scoped to its namespace and only decrypts there. The API reads them via `envFrom:
secretRef: kio-api`. Rotation/regeneration steps are in [staging.md](staging.md)
(`kubectl create secret ... | kubeseal ...`).

Harbor pull credentials live in the `harbor-registry` image-pull secret;
`task apply-stg` copies it from `kio-dev` into `kio-stg` if it's missing.

---

## Quick reference

| Task | What it does |
|------|--------------|
| `task version` | Show the current `v{VERSION}+build.{BUILD}` |
| `task bump:build` | Increment the build number (release-* runs this automatically) |
| `task release-dev` | Bump + build (`production`) + push + apply + rollout → `kio-dev` |
| `task release-stg BRANCH=<b>` | Bump + build (`test`, incl. suite) + push + stamp + apply + rollout → `kio-stg` |
| `task release-prd` | Bump + build (`production`) + push + stamp + apply + rollout + git tag → `kio` |
| `task build-test:api` | Build the API `test` image locally (`$HARBOR/kio-api:test`) |
| `task test:api:docker` | Build the `test` image and run the unit suite inside it |
| `task test:api` | Run the unit suite on the host via `uv` |
| `task db:migrate` | Run Alembic migrations against the dev compose stack |
| `task teardown-stg` | Delete the staging Deployments |

See `task --list` for the full set.
