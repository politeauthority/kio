# Authentication

## Overview

kio uses two separate authentication mechanisms:

- **Dashboard routes** (`/kiosks`, `/playlists`, SSE tickets, settings, etc.) — an
  OIDC JWT from **Authentik**, a static dev username/password, or an API key for
  programmatic clients (HACS, scripts).
- **Agent routes** (`/agent/*`) — NodeToken Bearer tokens (unchanged, not affected
  by dashboard auth).

Auth is implemented in `src/api/app/auth.py` and applied centrally in
`src/api/app/main.py` via `include_router(dependencies=[...])`.

---

## Login mechanisms

The API is the single place auth is configured. The UI asks it what is enabled at
boot (`GET /auth/config`, public) and renders the login page accordingly:

| Mechanism | API settings | Login page shows |
|---|---|---|
| Authentik (OIDC) | `AUTHENTIK_ISSUER` + `AUTHENTIK_CLIENT_ID` | "Sign in with Authentik" button |
| Dev login | `DEV_USERNAME` + `DEV_PASSWORD` | Username/password form |
| Both | all four | Button **and** form (form is the break-glass path) |
| Disabled | `AUTH_DISABLED=true` | No login page; everything is open (local dev only) |
| API keys | `API_KEYS` / Settings → API Keys | n/a — for non-browser clients |

When Authentik is the only mechanism, `/login` redirects straight to Authentik
without showing an intermediate page.

```
GET /auth/config
{
  "disabled": false,
  "oidc": {
    "authority": "https://auth.example.com/application/o/kio/",
    "client_id": "…",
    "display_name": "Authentik"
  },
  "dev_login": true
}
```

---

## Setting up Authentik

### 1. Create the application in Authentik

`scripts/authentik-setup.py` creates (or updates) a **public** OAuth2/OIDC
provider + application with the slug `kio`:

```bash
AUTHENTIK_URL=https://auth.example.com \
KIO_REDIRECT_URIS=https://kio.example.com/callback,https://stg.kio.example.com/callback \
python3 scripts/authentik-setup.py --token <admin-api-token>
```

Get an API token from Authentik: Admin Interface → Directory → Tokens → Create
(intent: **API**).

What it configures:

| Setting | Value |
|---|---|
| Application slug | `kio` |
| Issuer | `https://auth.example.com/application/o/kio/` |
| Client type | Public — Authorization Code + PKCE, no client secret |
| Redirect URIs | one `/callback` URL per kio environment (strict match) |
| Scopes | `openid profile email offline_access` |
| Access token validity | 24h |

`offline_access` is what lets the UI get a refresh token and renew the session in
the background; without it users get bounced through Authentik whenever the
access token expires.

Re-running the script is safe — it syncs the redirect URIs and scopes on the
existing provider.

**Who can sign in** is Authentik's job: bind a group or policy to the `kio`
application. kio trusts any user whose token Authentik issues for this client.

### 2. Configure the API

In `kubernetes-manifests/envs/<env>/api-configmap-patch.yaml` uncomment and fill:

```yaml
  AUTHENTIK_ISSUER: "https://auth.example.com/application/o/kio/"
  AUTHENTIK_CLIENT_ID: "<client id printed by the script>"
  AUTHENTIK_DISPLAY_NAME: "Authentik"   # optional, label on the login button
```

Nothing needs to change on `kio-ui`. Then:

```bash
kubectl apply -k kubernetes-manifests/envs/<env>/
kubectl rollout restart deployment/kio-api -n <namespace>
```

No image rebuild is needed — it is all runtime config.

### 3. Verify

- `curl https://api.kio.example.com/auth/config` shows the `oidc` block.
- Visit the dashboard → `/login` → "Sign in with Authentik" → Authentik login →
  back to `/callback` → lands on the page you originally asked for.
- The ⋯ menu shows the signed-in username; **Sign out** ends the Authentik
  session too and returns to `/login`.
- API logs show `Loaded N JWKS keys from Authentik` at startup.

### 4. (Optional) retire the dev login

Once Authentik works, remove `DEV_USERNAME` / `DEV_PASSWORD` from the sealed
secret and the form disappears from the login page. Keeping them is fine as a
break-glass path (the e2e suite also uses them).

---

## API keys (for HACS / programmatic access)

Keys can be managed in the dashboard (Settings → API Keys, stored hashed in the
DB) or set statically via `API_KEYS` (comma-separated, `kio_` prefix by
convention):

```bash
python3 -c "import secrets; print('kio_' + secrets.token_urlsafe(32))"
```

The API accepts a key as either `Authorization: Bearer kio_xxx` or
`X-API-Key: kio_xxx`.

---

## Local dev

`AUTH_DISABLED=true` in `src/api/.env` (already in `.env.example`) turns
everything off; the UI sees `disabled: true` and never shows a login page.

To exercise the real login flow locally, point the API at Authentik with a
redirect URI of `http://localhost:5173/callback` (add it to the provider), or
set `DEV_USERNAME`/`DEV_PASSWORD` for the form.

---

## How it works

### API (`src/api/app/auth.py`)

`require_dashboard_auth` tries, in order:

1. `X-API-Key` header matching a static or DB-managed key
2. `Authorization: Bearer <key>` (or `?token=`) matching a static or DB key
3. `Authorization: Bearer <jwt>` — dispatched on the token's `alg` header:
   - `HS256` → dev token issued by `POST /auth/login`, only if dev login is configured
   - `RS*`/`ES*` → Authentik token, only if `AUTHENTIK_ISSUER` is configured

Dispatching on the algorithm (rather than trying one validator then the other)
means both mechanisms can be on at once and an HS256 token can never be
validated against Authentik's public key (algorithm-confusion attack).

Authentik tokens are checked for signature, `exp`, `iss` (= `AUTHENTIK_ISSUER`)
and `aud` (= `AUTHENTIK_CLIENT_ID`, when set). The username is taken from
`preferred_username`, falling back to `email`, then `sub`.

JWKS keys are fetched from the issuer's OIDC discovery document at startup and
cached in memory. An unknown `kid` triggers a refetch (handles key rotation),
throttled to once per 60s so a flood of bad tokens can't hammer Authentik.

### UI (`src/ui/src/auth.js`)

`main.js` awaits `loadAuthConfig()` before the router runs. The route guard
sends unauthenticated users to `/login?returnTo=<path>`; `Login.vue` offers
whatever mechanisms are enabled and restores `returnTo` afterwards (only
in-app paths are honoured).

OIDC uses `oidc-client-ts` (Authorization Code + PKCE). Tokens live in
`sessionStorage`; `automaticSilentRenew` uses the refresh token, and a token
found expired on page load is renewed inline before the first API call. A `401`
from the API clears local credentials and returns to `/login`.

`OIDC_AUTHORITY` / `OIDC_CLIENT_ID` on the UI container (and `VITE_OIDC_*` for
`npm run dev`) are still honoured as a fallback when `/auth/config` is
unreachable, but are no longer needed.

### SSE

`EventSource` can't send headers, so the UI first calls
`POST /kiosks/{id}/sse-ticket` (authenticated) and opens the stream with the
short-lived single-use ticket — the bearer token never appears in a URL.
