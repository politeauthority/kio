// Canonical form for deciding whether two URLs are the same page. Mirrors
// normalize_url() in the API (src/api/app/services/url_names.py) so the
// dashboard's saved-URL matching agrees with the `current_url_name` the API
// reports to Home Assistant: scheme and host lower-cased, default ports
// dropped, trailing slash removed, fragment ignored. The query string is kept —
// `?panelId=3` is a different page. Anything unparseable compares as its
// stripped self.
export function normalizeUrl(input) {
  if (!input) return ''
  const raw = String(input).trim()
  let u
  try {
    u = new URL(raw)
  } catch {
    return raw.replace(/\/+$/, '')
  }
  if (!u.protocol || !u.host) return raw.replace(/\/+$/, '')
  // URL() already lower-cases scheme/host and drops default ports.
  const path = u.pathname.replace(/\/+$/, '')
  return `${u.protocol}//${u.host}${path}${u.search}`
}
