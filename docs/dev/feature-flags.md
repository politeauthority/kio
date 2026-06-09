# Feature Flags

Feature flags let us hide or show parts of the dashboard (and the features behind
them) at runtime, without a redeploy. They're toggled from **Settings → Feature
Flags** in the UI and stored in the database, so a flag flip takes effect for
everyone on their next page load.

They are **operator toggles, not per-user or per-kiosk gating** — every dashboard
user sees the same flag state. They're best for: rolling a half-finished feature
out behind a switch, turning off a section that's misbehaving in prod, or keeping
an environment's UI focused.

> Don't confuse these with a kiosk's **capabilities/features** (`display_power`,
> `cec`, `input_switch`). Those describe what a node's *hardware* supports and are
> detected per node. Feature flags are global UI/product switches.

---

## How it works (end to end)

```
feature_flags table ──GET /settings/feature-flags──> Pinia store ──isEnabled('x')──> v-if in components
        ▲                                                  
        └──PUT /settings/feature-flags/{key}── Settings UI toggle
```

1. The flag set is defined in **two** places (see "Adding a flag" for why):
   - API: `KNOWN_FLAGS` in `src/api/app/routers/feature_flags.py`
   - UI: `flagDefs` in `src/ui/src/settings/AppSettings.vue` (adds label + description)
2. The API serves current values from the `feature_flags` table, falling back to
   the `KNOWN_FLAGS` default for any key not yet written to the DB.
3. On app load, `App.vue` calls `featureFlags.load()` once, populating the Pinia
   store (`src/ui/src/stores/featureFlags.js`).
4. Components gate on `featureFlags.isEnabled('key')`.
5. Toggling in Settings calls `set()`, which `PUT`s the new value and updates the
   store in place.

### Fail-open behavior
The store's `isEnabled()` returns **`true` for any unknown key**:

```js
function isEnabled(key) {
  return key in flags.value ? flags.value[key] : true
}
```

So a flag is on by default, and if the flags request fails or the store hasn't
loaded yet, features stay visible rather than vanishing. Keep this in mind: a flag
only hides something once it's explicitly set to `false`.

---

## Using a flag

### In the UI (the common case)
Gate any element with the store's `isEnabled`:

```vue
<script setup>
import { useFeatureFlagsStore } from '../stores/featureFlags'
const featureFlags = useFeatureFlagsStore()
</script>

<template>
  <RouterLink v-if="featureFlags.isEnabled('playlists')" to="/playlists">Playlists</RouterLink>
  <div v-if="featureFlags.isEnabled('debug')">…debug links…</div>
</template>
```

The store is a singleton (Pinia) and is loaded once in `App.vue`, so any component
can read it without re-fetching. Examples live in `App.vue` (nav items) and
`KioskDetail.vue` (Browsers / Playlist / Debug sections).

### Server-side gating
There is **no** server-side enforcement today — flags only hide UI; the API
endpoints behind a feature stay reachable. If a feature ever needs to be truly
disabled (not just hidden), gate the relevant router/endpoint on the flag value
too. Treat the current flags as cosmetic/product switches, not security controls.

---

## Adding a new flag

It's a four-step change (API default, UI definition, gate the feature, ship a
default row). Example: adding a `kiosk_grouping` flag.

1. **API — register the key** in `KNOWN_FLAGS`
   (`src/api/app/routers/feature_flags.py`). The value is the default when the DB
   has no row. Unknown keys are rejected by the `PUT` endpoint, so this list is the
   source of truth for what's toggleable:
   ```python
   KNOWN_FLAGS = {
       "browser_management": True,
       "playlists": True,
       "debug": True,
       "kiosk_grouping": True,   # new
   }
   ```

2. **UI — describe it** in `flagDefs`
   (`src/ui/src/settings/AppSettings.vue`) so it shows up on the Settings page with
   a human label + description:
   ```js
   { key: 'kiosk_grouping', label: 'Kiosk Grouping',
     description: 'Show grouping controls on the kiosks list.' },
   ```

3. **Gate the feature** with `featureFlags.isEnabled('kiosk_grouping')` wherever it
   renders.

4. **Seed a default row (optional but recommended)** in a migration so the flag
   exists in the DB from the start (mirrors how `0018_feature_flags.py` seeded the
   originals):
   ```python
   op.execute("INSERT INTO feature_flags (key, enabled) VALUES ('kiosk_grouping', true)")
   ```
   This is optional because `KNOWN_FLAGS` already provides the default on read — but
   seeding makes the row visible/toggleable immediately and explicit in the DB.

> The key must match exactly across all three: `KNOWN_FLAGS`, `flagDefs`, and every
> `isEnabled('…')` call. A typo fails open (feature stays visible) and won't error,
> so it's easy to miss — grep for the key after adding it.

---

## Removing a flag

Once a feature is permanently on (or cut), retire the flag so it doesn't linger:
1. Remove the `isEnabled('key')` guards (keep or delete the feature as decided).
2. Remove the key from `KNOWN_FLAGS` and `flagDefs`.
3. Optional cleanup migration: `DELETE FROM feature_flags WHERE key = 'key'`.

---

## Reference

| Layer | File |
|---|---|
| DB model | `src/api/app/models/feature_flag.py` |
| Initial table + seed | `src/api/alembic/versions/0018_feature_flags.py` |
| API (defaults, list, update) | `src/api/app/routers/feature_flags.py` (`/settings/feature-flags`) |
| UI store | `src/ui/src/stores/featureFlags.js` |
| UI settings page | `src/ui/src/settings/AppSettings.vue` |
| Loaded at startup | `src/ui/src/App.vue` (`featureFlags.load()`) |

Current flags: `browser_management`, `playlists`, `debug`.

The `/settings/feature-flags` routes require dashboard auth (registered with
`_dashboard_auth` in `src/api/app/main.py`), so only authenticated dashboard users
can read or change flag state.
