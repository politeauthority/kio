import { API_URL } from '../config'
import { getAccessToken, clearSession, isAuthDisabled } from '../auth'

export function useApi() {
  async function apiFetch(path, options = {}) {
    const { headers = {}, raw = false, ...rest } = options

    const token = await getAccessToken()
    const authHeaders = token ? { Authorization: `Bearer ${token}` } : {}

    const res = await fetch(`${API_URL}${path}`, {
      headers: { 'Content-Type': 'application/json', ...authHeaders, ...headers },
      ...rest,
    })

    if (res.status === 401 && !isAuthDisabled()) {
      // Session is gone (expired, revoked, or the server's auth config changed).
      // Drop local credentials and send the user through the login page, which
      // will bring them back here afterwards.
      await clearSession()
      if (window.location.pathname !== '/login') {
        const returnTo = window.location.pathname + window.location.search
        const q = returnTo !== '/' ? `?returnTo=${encodeURIComponent(returnTo)}` : ''
        window.location.href = `/login${q}`
      }
      return
    }

    if (!res.ok) {
      const err = new Error(`API error ${res.status}`)
      err.status = res.status
      throw err
    }
    if (raw) return res
    if (res.status === 204) return null
    return res.json()
  }

  return { apiFetch }
}
