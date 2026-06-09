# Staging Environment

The staging environment (`kio-stg`) is an isolated Kubernetes namespace for testing branches before they reach production. It shares the `kio_dev` PostgreSQL database and MQTT broker but uses separate deployments, its own MQTT topic prefix (`kio/stg`), and the domains `stg.kio.example.local` / `api.stg.kio.example.local`.

## Deploying a branch

```bash
task release-stg BRANCH=feat/my-feature
```

This single command:
1. Builds the API image (`stg-latest`) with `VERSION=<branch>`
2. Pushes it to Harbor
3. Builds the UI image (`stg-latest`) with `KIO_BRANCH=<branch>` baked in
4. Pushes it to Harbor
5. Applies the kustomize overlay (`kubernetes-manifests/envs/stg/`)
6. Restarts both deployments and waits for rollout

## Branch banner

Whenever `KIO_BRANCH` is set in the UI image, a fixed amber bar appears at the top of every page showing the branch name. This is baked into the image at build time — it does not come from a k8s env var and cannot be overridden at runtime.

## Individual task commands

| Command | What it does |
|---|---|
| `task build-stg BRANCH=<branch>` | Build the API image tagged `stg-latest` |
| `task push-stg` | Push the API image to Harbor |
| `task build-ui-stg BRANCH=<branch>` | Build the UI image tagged `stg-latest` with the branch banner |
| `task push-ui-stg` | Push the UI image to Harbor |
| `task apply-stg` | `kubectl apply -k kubernetes-manifests/envs/stg/` |
| `task rollout-stg` | Restart both deployments in `kio-stg` and wait |
| `task release-stg BRANCH=<branch>` | Full pipeline — all of the above in order |
| `task teardown-stg` | Delete the kio-api and kio-ui deployments from `kio-stg` |

## URLs

| Service | URL |
|---|---|
| UI | http://stg.kio.example.local |
| API | http://api.stg.kio.example.local |

## Kubernetes manifest layout

```
kubernetes-manifests/envs/stg/
├── kustomization.yaml        # namespace kio-stg, images stg-latest
├── httproute.yaml            # HTTPRoutes for stg.kio.example.local and api.stg.kio.example.local
├── mqtt-patch.yaml           # MQTT_TOPIC_PREFIX: kio/stg
├── cors-patch.yaml           # CORS_ORIGINS: ["http://stg.kio.example.local"]
├── ui-patch.yaml             # API_URL: /api
└── secrets/
    └── sealed-api-secrets.yaml   # SealedSecret for DATABASE_URL (kio-stg namespace-scoped)
```

## Regenerating the SealedSecret

The `SealedSecret` in `secrets/sealed-api-secrets.yaml` is scoped to the `kio-stg` namespace — it will not decrypt in any other namespace. If you need to rotate the database password or recreate it:

```bash
kubectl create secret generic kio-api \
  --namespace kio-stg \
  --from-literal=DATABASE_URL='postgresql+asyncpg://<user>:<pass>@q-postgres-rw.q-postgres.svc.cluster.local:5432/kio_dev' \
  --dry-run=client -o yaml \
| kubeseal --format yaml --namespace kio-stg \
> kubernetes-manifests/envs/stg/secrets/sealed-api-secrets.yaml
```

Then commit the updated file and redeploy.
