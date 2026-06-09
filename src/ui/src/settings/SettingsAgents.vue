<template>
  <div>
    <div class="page-header">
      <div>
        <RouterLink to="/settings" class="text-muted text-sm" style="display: inline-flex; align-items: center; gap: 4px; margin-bottom: 0.4rem">
          ← Settings
        </RouterLink>
        <h1 class="page-title">Agents</h1>
      </div>
      <button class="btn btn-primary" style="min-width: 64px" :disabled="saving || loading" @click="save">
        {{ saving ? 'Saving…' : 'Save' }}
      </button>
    </div>

    <div class="card" style="max-width: 560px">
      <p class="text-xs text-muted" style="margin-bottom: 1.25rem">
        System-wide settings affecting node health monitoring and log retention.
      </p>
      <div v-if="loading" class="text-muted text-sm">Loading…</div>
      <div v-else style="display: flex; flex-direction: column; gap: var(--space-md)">
        <div
          v-for="field in agentFields"
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

const agentFields = [
  { key: 'node_offline_threshold_seconds', label: 'Node health timeout', description: 'A node with no heartbeat for this long is marked offline.', unit: 'sec', min: 10, max: 3600 },
  { key: 'event_log_purge_days', label: 'Event log retention', description: 'Event-log entries older than this are purged.', unit: 'days', min: 1, max: 365 },
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
    for (const f of agentFields) payload[f.key] = Number(settings.value[f.key])
    settings.value = await apiFetch('/settings/agent', {
      method: 'PUT',
      body: JSON.stringify(payload),
    })
    toast.add('Settings saved', 'success')
  } catch (e) {
    toast.add(e.status === 422 ? 'Invalid value — check the ranges' : 'Failed to save settings', 'error')
  } finally {
    saving.value = false
  }
}

load()
</script>
