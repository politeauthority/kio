<template>
  <div>
    <div class="page-header">
      <div>
        <RouterLink to="/settings" class="text-muted text-sm" style="display: inline-flex; align-items: center; gap: 4px; margin-bottom: 0.4rem">
          ← Settings
        </RouterLink>
        <h1 class="page-title">Timing</h1>
      </div>
      <button class="btn btn-primary" style="min-width: 64px" :disabled="saving || loading" @click="save">
        {{ saving ? 'Saving…' : 'Save' }}
      </button>
    </div>

    <div class="card" style="max-width: 560px">
      <p class="text-xs text-muted" style="margin-bottom: 1.25rem">
        Default intervals applied to every node. Saving pushes changes to online nodes immediately;
        others pick them up on their next checkin. Individual nodes can override heartbeat and jitter
        on their edit page.
      </p>
      <div v-if="loading" class="text-muted text-sm">Loading…</div>
      <div v-else style="display: flex; flex-direction: column; gap: var(--space-md)">
        <div
          v-for="field in timingFields"
          :key="field.key"
          style="display: flex; align-items: center; justify-content: space-between; gap: 1rem"
        >
          <div>
            <div class="text-sm" style="font-weight: 500">{{ field.label }}</div>
            <div class="text-xs text-muted" style="margin-top: 0.2rem">{{ field.description }}</div>
          </div>
          <div style="display: flex; align-items: center; gap: 0.5rem; flex-shrink: 0">
            <input
              v-model.number="settings[field.key]"
              type="number"
              class="form-input"
              :min="field.min"
              :max="field.max"
              style="width: 110px"
            />
            <span class="text-xs text-muted" style="width: 44px">{{ field.unit }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { RouterLink } from 'vue-router'
import { useToastStore } from '../stores/toast'
import { useApi } from '../composables/useApi'

const toast = useToastStore()
const { apiFetch } = useApi()
const loading = ref(true)
const saving = ref(false)
const settings = ref({})

const timingFields = [
  { key: 'heartbeat_interval_seconds', label: 'Heartbeat interval', description: 'How often nodes report status.', unit: 'sec', min: 5, max: 3600 },
  { key: 'heartbeat_jitter_seconds', label: 'Heartbeat jitter', description: 'Random spread added per node so they don\'t all check in at once.', unit: 'sec', min: 0, max: 300 },
  { key: 'metadata_interval_seconds', label: 'Metadata interval', description: 'How often nodes send full metadata (display, inputs, IP).', unit: 'sec', min: 60, max: 86400 },
  { key: 'settings_checkin_seconds', label: 'Settings checkin', description: 'How often nodes re-fetch these settings.', unit: 'sec', min: 30, max: 86400 },
]

async function load() {
  try {
    settings.value = await apiFetch('/settings/agent')
  } catch {
    toast.add('Failed to load settings', 'error')
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const payload = {}
    for (const f of timingFields) payload[f.key] = Number(settings.value[f.key])
    settings.value = await apiFetch('/settings/agent', {
      method: 'PUT',
      body: JSON.stringify(payload),
    })
    toast.add('Timing settings saved', 'success')
  } catch (e) {
    toast.add(e.status === 422 ? 'Invalid value — check the ranges' : 'Failed to save settings', 'error')
  } finally {
    saving.value = false
  }
}

load()
</script>
