import { UserManager, WebStorageStateStore } from 'oidc-client-ts'

const _raw_authority = window.OIDC_AUTHORITY
const _raw_clientId = window.OIDC_CLIENT_ID
const authority = (_raw_authority && _raw_authority !== '__OIDC_AUTHORITY__') ? _raw_authority : ''
const clientId = (_raw_clientId && _raw_clientId !== '__OIDC_CLIENT_ID__') ? _raw_clientId : ''

export const AUTH_ENABLED = Boolean(authority && clientId)

const DEV_TOKEN_KEY = 'kio_dev_token'

// ---------------------------------------------------------------------------
// OIDC (production)
// ---------------------------------------------------------------------------

let _manager = null

function getManager() {
  if (!_manager && AUTH_ENABLED) {
    _manager = new UserManager({
      authority,
      client_id: clientId,
      redirect_uri: `${window.location.origin}/callback`,
      post_logout_redirect_uri: window.location.origin,
      response_type: 'code',
      scope: 'openid profile email',
      userStore: new WebStorageStateStore({ store: window.sessionStorage }),
    })
  }
  return _manager
}

export async function getUser() {
  if (!AUTH_ENABLED) return null
  return getManager().getUser()
}

export async function handleCallback() {
  return getManager().signinRedirectCallback()
}

export async function logout() {
  if (AUTH_ENABLED) {
    await getManager().signoutRedirect()
  } else {
    devLogout()
  }
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
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) throw new Error('Invalid credentials')
  const { access_token } = await res.json()
  sessionStorage.setItem(DEV_TOKEN_KEY, access_token)
}

// ---------------------------------------------------------------------------
// Shared
// ---------------------------------------------------------------------------

export async function getAccessToken() {
  if (AUTH_ENABLED) {
    const user = await getUser()
    return user?.access_token ?? null
  }
  return getDevToken()
}

export async function isAuthenticated() {
  if (AUTH_ENABLED) {
    const user = await getUser()
    return Boolean(user && !user.expired)
  }
  return Boolean(getDevToken())
}

export async function login() {
  if (AUTH_ENABLED) {
    await getManager().signinRedirect()
  }
  // Dev: route guard handles redirect to /login
}
