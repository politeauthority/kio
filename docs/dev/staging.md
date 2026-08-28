# Staging Environment

`kio-stg` is a staging namespace you deploy **by hand** from a laptop with the Taskfile
and tear down the same way. It is deliberately **not** GitOps-managed and has no CI
pipeline: nothing deploys to it unless you run a task. It has its own PostgreSQL
database (`kio_stg` in q-postgres, GitOps-owned in private-ops), the MQTT topic prefix
`kio/stg`, and the LAN hosts `stg.kio.colfax.int` / `api.stg.kio.colfax.int` (private CA).

## Deploy a branch

```bash
task release-stg BRANCH=feat/my-feature
```

Builds the API image (`test` target — ships the unit suite) and the UI image (branch
banner baked in) tagged `stg-feat-my-feature`, pushes them to Harbor, applies
`kubernetes-manifests/envs/stg/`, and restarts/waits for both Deployments.

```bash
task stg-deploy TAG=stg-feat-my-feature   # (re)deploy an already-pushed tag with the migrate gate
task stg-teardown                          # delete the Deployments + migrate Job; namespace and secrets stay
```

`stg-deploy` is the stricter path: it deletes the previous (immutable) `kio-migrate` Job,
applies, waits for the new Job to **succeed** before waiting for the rollout, so a failed
migration stops the deploy instead of leaving a half-rolled namespace. It stamps the tag
into `envs/stg/kustomization.yaml` in place — don't commit that; the committed tag is
`stg-main`.

## Running the e2e suite against it

```bash
task test:e2e:install          # once: uv sync + playwright chromium
KIO_API_URL=https://api.stg.kio.colfax.int KIO_UI_URL=https://stg.kio.colfax.int \
KIO_USERNAME=<DEV_USERNAME> KIO_PASSWORD=<DEV_PASSWORD> task test:e2e
```

(or put those in `tests/e2e/.env`). The credentials are the `DEV_USERNAME` /
`DEV_PASSWORD` sealed into `envs/stg/secrets/sealed-api-secrets.yaml`.

## Individual task commands

| Command | What it does |
|---|---|
| `task build-stg BRANCH=<b>` / `task push-stg BRANCH=<b>` | Build / push `kio-api:stg-<b>` (+ immutable `-build.N` tag) |
| `task build-ui-stg BRANCH=<b>` / `task push-ui-stg BRANCH=<b>` | Build / push `kio-ui:stg-<b>` with the branch banner |
| `task apply-stg` | `kubectl apply -k kubernetes-manifests/envs/stg/` |
| `task rollout-stg` | Restart both Deployments in `kio-stg` and wait |
| `task release-stg BRANCH=<b>` | All of the above in order |
| `task stg-deploy TAG=<tag>` | Deploy a tag with the migrate hard-gate |
| `task stg-teardown` | Delete the Deployments + Job |

## Branch banner

Whenever `KIO_BRANCH` is set in the UI image, a fixed amber bar appears at the top of
every page showing the branch name. It is baked in at build time and cannot be
overridden at runtime.

## Manifest layout

```
kubernetes-manifests/envs/stg/
├── kustomization.yaml         # namespace kio-stg, images stg-main
├── ingressroute.yaml          # traefik-private routes + private-ca Certificate
├── api-configmap-patch.yaml
├── cors-patch.yaml
├── mqtt-patch.yaml            # MQTT_TOPIC_PREFIX: kio/stg
├── nodeport-patch.yaml
├── ui-patch.yaml              # API_URL: /api
└── secrets/
    ├── sealed-api-secrets.yaml      # DATABASE_URL (kio_stg), MQTT_*, DEV_* — scoped to ns kio-stg
    └── sealed-harbor-registry.yaml  # image pull secret — scoped to ns kio-stg
```

## Rotating the staging secrets

The SealedSecrets only decrypt in namespace `kio-stg`. To rotate:

```bash
kubectl create secret generic kio-api -n kio-stg \
  --from-literal=DATABASE_URL='postgresql+asyncpg://kio_stg:<pw>@q-postgres-rw.q-postgres.svc.cluster.local:5432/kio_stg' \
  --from-literal=MQTT_HOST=... --from-literal=MQTT_PORT=1883 --from-literal=MQTT_TOPIC_PREFIX=kio/stg \
  --from-literal=DEV_USERNAME=... --from-literal=DEV_PASSWORD=... \
  --dry-run=client -o yaml | kubeseal --format yaml > kubernetes-manifests/envs/stg/secrets/sealed-api-secrets.yaml
```

The `kio_stg` DB password is sealed in private-ops
`q-postgres/base/secrets/secret-kio-stg-postgres-user.yaml`; change both together.
