# Authentication

## Overview

kio uses two separate authentication mechanisms:

- **Dashboard routes** (`/kiosks`, `/playlists`, SSE, etc.) — OIDC JWT from Authentik, or static API keys for programmatic clients (HACS, scripts)
- **Agent routes** (`/agent/*`) — NodeToken Bearer tokens (unchanged, not affected by dashboard auth)

Auth is implemented in `api/app/auth.py` and applied centrally in `api/app/main.py` via `include_router(dependencies=[...])`.

---

## Current state (as of v0.4.0)

Auth is deployed but **disabled** in production (`AUTH_DISABLED=true`). The Authentik application and OIDC provider are created and configured; they just need to be turned on.

```
kubernetes-manifests/envs/prd/auth-patch-api.yaml   ← AUTH_DISABLED=true here
kubernetes-manifests/envs/prd/auth-patch-ui.yaml    ← OIDC vars blanked here
```

---

## Authentik setup (already done)

The kio application was created in Authentik via `scripts/authentik-setup.py`:

| Setting | Value |
|---|---|
| Application slug | `kio` |
| OIDC issuer | `https://auth.example.com/application/o/kio/` |
| Client type | Public (PKCE, no client secret) |
| Redirect URI | `http://kio.example.local/callback` |
| Client ID | `&lt;your-oidc-client-id&gt;` |

To re-run or update the Authentik config:

```bash
python3 scripts/authentik-setup.py --token <admin-api-token>
```

Get an API token: Authentik admin UI → Admin Interface → Directory → Tokens → Create (intent: API).

---

## Turning auth on

No rebuild is needed — auth is controlled entirely by env vars injected at runtime.

**1. Edit the k8s patches:**

`kubernetes-manifests/envs/prd/auth-patch-api.yaml` — remove `AUTH_DISABLED`:

```yaml
env:
  - name: AUTHENTIK_ISSUER
    value: "https://auth.example.com/application/o/kio/"
  # AUTH_DISABLED removed
```

`kubernetes-manifests/envs/prd/auth-patch-ui.yaml` — restore OIDC values:

```yaml
env:
  - name: OIDC_AUTHORITY
    value: "https://auth.example.com/application/o/kio/"
  - name: OIDC_CLIENT_ID
    value: "&lt;your-oidc-client-id&gt;"
```

**2. Apply:**

```bash
kubectl apply -k kubernetes-manifests/envs/prd/
kubectl rollout restart deployment/kio-api -n kio
kubectl rollout restart deployment/kio-ui -n kio
```

**3. Test the login flow:**

Visit `http://kio.example.local` — the UI should redirect to `auth.example.com` for login. After authenticating, Authentik redirects back to `/callback` which completes the session and lands you on the dashboard.

Authentik provides the login page — there is no separate login UI in kio.

---

## API keys (for HACS / programmatic access)

Static API keys can be added to the production secret for use by non-browser clients like the Home Assistant integration.

**1. Generate a key** (use a `kio_` prefix by convention):

```bash
python3 -c "import secrets; print('kio_' + secrets.token_urlsafe(32))"
```

**2. Add to the sealed secret:**

```bash
# Decrypt, add API_KEYS=kio_xxx, re-seal
kubectl get secret kio-api -n kio -o json | kubeseal --format yaml > sealed.yaml
# (or use your existing sealing workflow)
```

**3. The API accepts the key as either:**
- `Authorization: Bearer kio_xxx`
- `X-API-Key: kio_xxx`

---

## Local dev

Set `AUTH_DISABLED=true` in `api/.env` (already in `.env.example`). Leave the VITE OIDC vars unset — `AUTH_ENABLED` will be false in the UI and no login redirect occurs.

---

## How it works

### API (`api/app/auth.py`)

`require_dashboard_auth` tries in order:

1. `X-API-Key` header matching a key in `API_KEYS`
2. `Authorization: Bearer <static-key>` matching `API_KEYS`
3. `Authorization: Bearer <jwt>` validated against Authentik's JWKS

JWKS keys are fetched from Authentik's OIDC discovery endpoint at startup and cached in memory. On an unknown `kid`, they refresh automatically (handles key rotation).

### UI (`ui/src/auth.js`)

Uses `oidc-client-ts` with the Authorization Code + PKCE flow. `AUTH_ENABLED` is false when either OIDC env var is blank, which skips all auth logic. The route guard in `main.js` redirects unauthenticated users to Authentik login; the `/callback` route completes the flow.

OIDC config is injected at container startup by `docker-entrypoint.sh` (same `__VAR__` substitution pattern as `API_URL`) so the same image works in all environments.
