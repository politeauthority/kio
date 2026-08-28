# Staging Environment

`kio-stg` is a **shared** staging namespace: one PR at a time is deployed into it for
regression testing and manual poking. It has its own PostgreSQL database (`kio_stg`
in q-postgres), the MQTT topic prefix `kio/stg`, and the LAN hosts
`stg.kio.colfax.int` / `api.stg.kio.colfax.int` (private CA).

## Who owns what

| Piece | Owner | Where |
|---|---|---|
| Namespace, `kio-stg-ci` ServiceAccount + Role, SealedSecrets (`kio-api` → `kio_stg` DB, `harbor-registry`) | ArgoCD | private-ops `kio/stg/` (Application `kio-stg` in colfax-ops) |
| Deployments, Services, migrate Job, routes, ConfigMap | **CI / you** | this repo, `kubernetes-manifests/envs/stg/` |
| `kio_stg` database + role | ArgoCD | private-ops `q-postgres/` |

Nothing in `envs/stg/` contains a secret any more.

## CI: label a PR `stg-env`

`.github/workflows/stg.yaml` runs when a PR carries the **`stg-env`** label (and on every
new commit while it does):

1. **build** — `build-stg`/`build-ui-stg` with `BRANCH=pr-<N>` → `kio-api:stg-pr-<N>`
   (API `test` target: ships the unit suite) and `kio-ui:stg-pr-<N>` (branch banner).
2. **deploy-regression** — `task stg-deploy TAG=stg-pr-<N>`: stamps the tag, deletes the
   old migrate Job, `kubectl apply -k envs/stg`, waits for `kio-migrate` to **succeed**
   (hard gate) and both Deployments to roll; then `task test:e2e:api` + `test:e2e:ui`
   against the in-cluster Services (`http://kio-api.kio-stg.svc:8000`, `http://kio-ui.kio-stg.svc:8080`).
3. **promote** — manual approval of the `staging` GitHub environment.

Runs are serialized repo-wide (`concurrency: stg-shared-namespace`) because the namespace
is shared. The last deployed PR stays up until the next labeled PR replaces it.

### Repo secrets the workflow needs (one-time)

| Name | Value |
|---|---|
| `STG_KUBECONFIG` | `scripts/stg-kubeconfig.sh \| gh secret set STG_KUBECONFIG -R politeauthority/kio` — a kubeconfig for the `kio-stg-ci` ServiceAccount (namespace-scoped; in-cluster API server address) |
| `STG_USERNAME` / `STG_PASSWORD` | the `DEV_USERNAME` / `DEV_PASSWORD` sealed into kio-stg's `kio-api` secret (private-ops) |
| `HARBOR_PASSWORD` | already set (shared `robot$ci`) |

Plus a `staging` environment with required reviewers (Settings → Environments) and the
`stg-env` label.

## From a laptop

```bash
task release-stg BRANCH=feat/my-feature   # build + push stg-<branch> images, apply, rollout
task stg-deploy TAG=stg-pr-12             # (re)deploy an existing tag with the migrate gate
task stg-teardown                         # scale the app to zero; namespace/secrets stay
task test:e2e KIO_API_URL=https://api.stg.kio.colfax.int KIO_UI_URL=https://stg.kio.colfax.int
```

`stg-deploy` edits `envs/stg/kustomization.yaml` in place (`kustomize edit set image`) —
don't commit that change; the committed tag is `stg-main`.

## Branch banner

Whenever `KIO_BRANCH` is set in the UI image, a fixed amber bar appears at the top of
every page showing the branch name. It is baked in at build time and cannot be
overridden at runtime.

## Rotating the staging secrets

Re-seal into private-ops `kio/stg/sealed-api-secrets.yaml` (namespace `kio-stg`):

```bash
kubectl create secret generic kio-api -n kio-stg \
  --from-literal=DATABASE_URL='postgresql+asyncpg://kio_stg:<pw>@q-postgres-rw.q-postgres.svc.cluster.local:5432/kio_stg' \
  --from-literal=MQTT_HOST=... --from-literal=MQTT_PORT=1883 --from-literal=MQTT_TOPIC_PREFIX=kio/stg \
  --from-literal=DEV_USERNAME=... --from-literal=DEV_PASSWORD=... \
  --dry-run=client -o yaml | kubeseal --format yaml > kio/stg/sealed-api-secrets.yaml
```

The `kio_stg` DB password is the one sealed in private-ops
`q-postgres/base/secrets/secret-kio-stg-postgres-user.yaml`; if it changes, both
secrets must be re-sealed together.
