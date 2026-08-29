import { UserManager, WebStorageStateStore } from 'oidc-client-ts'
import { API_URL } from './config'

// ---------------------------------------------------------------------------
// Auth config
//
// The API is the source of truth for which login mechanisms exist
// (GET /auth/config). That keeps a single place to configure Authentik —
// AUTHENTIK_ISSUER / AUTHENTIK_CLIENT_ID on the API — instead of mirroring the
// same values into the UI container. The legacy OIDC_AUTHORITY / OIDC_CLIENT_ID
// injection (and VITE_OIDC_* for `npm run dev`) is kept as a fallback.
// ---------------------------------------------------------------------------

const DEV_TOKEN_KEY = 'kio_dev_token'
// Which mechanism signed the user in last. Lets /login skip straight to Authentik
// on a fresh tab instead of showing the button again.
const LAST_LOGIN_KEY = 'kio_last_login'

function _injected(name, placeholder) {
  const v = window[name]
  return v && v !== placeholder ? v : ''
}

function _fallbackConfig() {
  const authority = _injected('OIDC_AUTHORITY', '__OIDC_AUTHORITY__') || import.meta.env.VITE_OIDC_AUTHORITY || ''
  const clientId = _injected('OIDC_CLIENT_ID', '__OIDC_CLIENT_ID__') || import.meta.env.VITE_OIDC_CLIENT_ID || ''
  return {
    disabled: false,
    oidc: authority && clientId ? { authority, client_id: clientId, display_name: 'Authentik' } : null,
    dev_login: true,
  }
}

let _config = null

export async function loadAuthConfig() {
  if (_config) return _config
  try {
    const res = await fetch(`${API_URL}/auth/config`)
    if (res.ok) {
      const cfg = await res.json()
      // A fresh API without a client_id can't drive PKCE — treat as not configured.
      if (cfg.oidc && !cfg.oidc.client_id) cfg.oidc = null
      _config = cfg
      return _config
    }
  } catch {
    /* API unreachable — fall through */
  }
  _config = _fallbackConfig()
  return _config
}

export function authConfig() {
  return _config ?? _fallbackConfig()
}

export function isAuthDisabled() {
  return Boolean(authConfig().disabled)
}

export function isOidcEnabled() {
  return Boolean(authConfig().oidc)
}

export function isDevLoginEnabled() {
  return Boolean(authConfig().dev_login)
}

// ---------------------------------------------------------------------------
// OIDC (Authentik) — Authorization Code + PKCE
// ---------------------------------------------------------------------------

let _manager = null

function getManager() {
  const oidc = authConfig().oidc
  if (!_manager && oidc) {
    _manager = new UserManager({
      authority: oidc.authority,
      client_id: oidc.client_id,
      redirect_uri: `${window.location.origin}/callback`,
      post_logout_redirect_uri: `${window.location.origin}/login`,
      response_type: 'code',
      // offline_access asks Authentik for a refresh token so the session can be
      // renewed in the background instead of bouncing through a full redirect
      // every time the (short-lived) access token expires.
      scope: 'openid profile email offline_access',
      automaticSilentRenew: true,
      // Authentik does not expose an OP check-session iframe; leave it off to
      // avoid console noise and spurious sign-outs.
      monitorSession: false,
      // localStorage, not sessionStorage: a session-scoped store is per tab and
      // gone when the tab closes, so every new tab or browser start had to go
      // back through Authentik — and back through its login form whenever the
      // Authentik cookie had lapsed too. With the user (and its refresh token)
      // in localStorage every tab shares one session, and getUser() renews it in
      // place for as long as the refresh token lasts.
      userStore: new WebStorageStateStore({ store: window.localStorage }),
    })
  }
  return _manager
}

export async function getUser() {
  const mgr = getManager()
  if (!mgr) return null
  let user = await mgr.getUser()
  if (user?.expired && user.refresh_token) {
    // Page loaded (or tab woke up) after the access token lapsed — renew inline.
    try {
      user = await mgr.signinSilent()
    } catch {
      // The store is shared across tabs, so another tab may have renewed (and
      // rotated the refresh token) while this one was trying. Re-read before
      // deciding the session is dead — dropping the user here would sign every
      // tab out.
      const fresh = await mgr.getUser()
      if (fresh && !fresh.expired) return fresh
      await mgr.removeUser()
      user = null
    }
  }
  return user
}

export async function handleCallback() {
  const user = await getManager().signinRedirectCallback()
  rememberLogin('oidc')
  return user?.state?.returnTo || '/'
}

function rememberLogin(method) {
  try {
    localStorage.setItem(LAST_LOGIN_KEY, method)
  } catch {
    /* storage unavailable — the login page just shows the button */
  }
}

/** True when the last successful sign-in on this browser went through Authentik. */
export function lastLoginWasOidc() {
  try {
    return localStorage.getItem(LAST_LOGIN_KEY) === 'oidc'
  } catch {
    return false
  }
}

/** Kick off the redirect to Authentik. `returnTo` is restored after the callback. */
export async function oidcLogin(returnTo = '/') {
  await getManager().signinRedirect({ state: { returnTo } })
}

// ---------------------------------------------------------------------------
// Dev auth (static credentials)
// ---------------------------------------------------------------------------

export function getDevToken() {
  return sessionStorage.getItem(DEV_TOKEN_KEY)
}

export function devLogout() {
  sessionStorage.removeItem(DEV_TOKEN_KEY)
}

export async function devLogin(username, password) {
  const res = await fetch(`${API_URL}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) throw new Error('Invalid credentials')
  const { access_token } = await res.json()
  sessionStorage.setItem(DEV_TOKEN_KEY, access_token)
  rememberLogin('dev')
}

// ---------------------------------------------------------------------------
// Shared
// ---------------------------------------------------------------------------

export async function getAccessToken() {
  if (isAuthDisabled()) return null
  const dev = getDevToken()
  if (dev) return dev
  if (isOidcEnabled()) {
    const user = await getUser()
    return user?.access_token ?? null
  }
  return null
}

export async function isAuthenticated() {
  if (isAuthDisabled()) return true
  if (getDevToken()) return true
  if (isOidcEnabled()) {
    const user = await getUser()
    return Boolean(user && !user.expired)
  }
  return false
}

/** Display name of the signed-in user, or null. */
export async function currentUserName() {
  if (getDevToken()) {
    try {
      const payload = JSON.parse(atob(getDevToken().split('.')[1].replace(/-/g, '+').replace(/_/g, '/')))
      return payload.sub || 'dev'
    } catch {
      return 'dev'
    }
  }
  if (isOidcEnabled()) {
    const user = await getUser()
    const p = user?.profile
    return p?.preferred_username || p?.name || p?.email || null
  }
  return null
}

/** Drop local credentials (dev token and any cached OIDC user). Never redirects. */
export async function clearSession() {
  devLogout()
  const mgr = getManager()
  if (mgr) await mgr.removeUser()
}

export async function logout() {
  const wasDev = Boolean(getDevToken())
  await clearSession()
  // An explicit sign-out means the next visit should get the choice again.
  try {
    localStorage.removeItem(LAST_LOGIN_KEY)
  } catch {
    /* ignore */
  }
  if (!wasDev && isOidcEnabled()) {
    try {
      // Ends the Authentik session too; lands on /login afterwards.
      await getManager().signoutRedirect()
      return true
    } catch {
      /* no end_session_endpoint or network error — local sign-out is enough */
    }
  }
  return false
}

/** Build the /login route that will bring the user back to `returnTo` afterwards. */
export function loginRoute(returnTo) {
  const query = returnTo && returnTo !== '/' ? { returnTo } : {}
  return { path: '/login', query }
}
