import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useApi } from '../composables/useApi'

export const useFeatureFlagsStore = defineStore('featureFlags', () => {
  const flags = ref({})
  const { apiFetch } = useApi()

  async function load() {
    try {
      const data = await apiFetch('/settings/feature-flags')
      flags.value = Object.fromEntries(data.map(f => [f.key, f.enabled]))
    } catch {}
  }

  async function set(key, enabled) {
    await apiFetch(`/settings/feature-flags/${key}`, {
      method: 'PUT',
      body: JSON.stringify({ enabled }),
    })
    flags.value = { ...flags.value, [key]: enabled }
  }

  // Fail open: unknown flags default to true
  function isEnabled(key) {
    return key in flags.value ? flags.value[key] : true
  }

  return { flags, load, set, isEnabled }
})
