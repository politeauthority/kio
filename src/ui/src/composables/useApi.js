import { API_URL } from '../config'
import { getAccessToken, login, AUTH_ENABLED } from '../auth'

export function useApi() {
  async function apiFetch(path, options = {}) {
    const { headers = {}, raw = false, ...rest } = options

    const token = await getAccessToken()
    const authHeaders = token ? { Authorization: `Bearer ${token}` } : {}

    const res = await fetch(`${API_URL}${path}`, {
      headers: { 'Content-Type': 'application/json', ...authHeaders, ...headers },
      ...rest,
    })

    if (res.status === 401) {
      if (AUTH_ENABLED) {
        await login()
      } else if (window.location.pathname !== '/login') {
        window.location.href = '/login'
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
