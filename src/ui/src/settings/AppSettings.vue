<template>
  <div>
    <div class="page-header">
      <h1 class="page-title">Settings</h1>
    </div>

    <div class="card" style="max-width: 560px">
      <div class="card-header">Feature Flags</div>
      <div style="display: flex; flex-direction: column; gap: 0">
        <div
          v-for="(flag, idx) in flagDefs"
          :key="flag.key"
          style="display: flex; align-items: center; justify-content: space-between; padding: 0.875rem 0"
          :style="idx < flagDefs.length - 1 ? 'border-bottom: 1px solid var(--border)' : ''"
        >
          <div>
            <div class="text-sm" style="font-weight: 500">{{ flag.label }}</div>
            <div class="text-xs text-muted" style="margin-top: 0.2rem">{{ flag.description }}</div>
          </div>
          <button
            class="btn"
            :class="flagStore.isEnabled(flag.key) ? 'btn-primary' : 'btn-secondary'"
            style="min-width: 64px"
            :disabled="saving === flag.key"
            @click="toggle(flag.key)"
          >
            {{ flagStore.isEnabled(flag.key) ? 'On' : 'Off' }}
          </button>
        </div>
      </div>
    </div>

    <div class="card mt-lg" style="max-width: 560px">
      <div class="card-header" style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0">
        <span>Agents</span>
        <button class="btn btn-primary" style="min-width: 64px" :disabled="savingAgents || loadingAgents" @click="saveAgents">
          {{ savingAgents ? 'Saving…' : 'Save' }}
        </button>
      </div>
      <p class="text-xs text-muted" style="margin-top: 0.5rem; margin-bottom: 1rem">
        Defaults applied to every node. Saving pushes changes to online nodes immediately;
        others pick them up on their next checkin. Heartbeat and jitter can be overridden per node on its edit page.
      </p>

      <div v-if="loadingAgents" class="text-muted text-sm">Loading…</div>
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
              v-model.number="agentSettings[field.key]"
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

    <!-- API Keys -->
    <div class="card mt-lg" style="max-width: 560px">
      <div class="card-header" style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0">
        <span>API Keys</span>
        <button class="btn btn-primary" style="min-width: 64px" @click="showNewKeyForm = true">
          Generate
        </button>
      </div>
      <p class="text-xs text-muted" style="margin-top: 0.5rem; margin-bottom: 1rem">
        API keys allow external systems (like Home Assistant) to access the kio API.
        The token is shown only once when created.
      </p>

      <!-- New key form -->
      <div v-if="showNewKeyForm" style="display: flex; gap: 0.5rem; margin-bottom: 1rem">
        <input
          v-model="newKeyName"
          class="form-input"
          placeholder="Name, e.g. Home Assistant"
          style="flex: 1"
          @keyup.enter="createKey"
        />
        <button class="btn btn-primary" :disabled="!newKeyName.trim() || creatingKey" @click="createKey">
          {{ creatingKey ? '…' : 'Create' }}
        </button>
        <button class="btn btn-secondary" @click="showNewKeyForm = false; newKeyName = ''">
          Cancel
        </button>
      </div>

      <!-- One-time token reveal -->
      <div v-if="newTokenValue" style="margin-bottom: 1rem; padding: 0.75rem; background: var(--surface-2, #1e1e1e); border-radius: 6px; border: 1px solid var(--border)">
        <div class="text-xs text-muted" style="margin-bottom: 0.4rem">
          Copy this token now — it will not be shown again.
        </div>
        <div style="display: flex; align-items: center; gap: 0.5rem">
          <code style="flex: 1; font-size: 0.8rem; word-break: break-all">{{ newTokenValue }}</code>
          <button class="btn btn-secondary" style="flex-shrink: 0" @click="copyToken">
            {{ copied ? 'Copied!' : 'Copy' }}
          </button>
        </div>
        <button class="btn btn-secondary" style="margin-top: 0.5rem; font-size: 0.75rem" @click="newTokenValue = null; copied = false">
          Done
        </button>
      </div>

      <div v-if="loadingKeys" class="text-muted text-sm">Loading…</div>
      <div v-else-if="apiKeys.length === 0" class="text-muted text-sm">No API keys yet.</div>
      <div v-else style="display: flex; flex-direction: column; gap: 0">
        <div
          v-for="(key, idx) in apiKeys"
          :key="key.id"
          style="display: flex; align-items: center; justify-content: space-between; padding: 0.75rem 0"
          :style="idx < apiKeys.length - 1 ? 'border-bottom: 1px solid var(--border)' : ''"
        >
          <div>
            <div class="text-sm" style="font-weight: 500">{{ key.name }}</div>
            <div class="text-xs text-muted" style="margin-top: 0.15rem">
              Created {{ formatDate(key.created_at) }}
              <span v-if="key.last_used_at"> · Last used {{ formatDate(key.last_used_at) }}</span>
              <span v-else> · Never used</span>
            </div>
          </div>
          <button
            class="btn btn-danger"
            style="min-width: 64px"
            :disabled="revokingKey === key.id"
            @click="revokeKey(key)"
          >
            {{ revokingKey === key.id ? '…' : 'Revoke' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useFeatureFlagsStore } from '../stores/featureFlags'
import { useToastStore } from '../stores/toast'
import { useApi } from '../composables/useApi'

const flagStore = useFeatureFlagsStore()
const toast = useToastStore()
const { apiFetch } = useApi()
const saving = ref(null)

// --- API Keys ---
const apiKeys = ref([])
const loadingKeys = ref(true)
const showNewKeyForm = ref(false)
const newKeyName = ref('')
const creatingKey = ref(false)
const newTokenValue = ref(null)
const copied = ref(false)
const revokingKey = ref(null)

function formatDate(iso) {
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

async function loadKeys() {
  try {
    apiKeys.value = await apiFetch('/api-keys')
  } catch {
    toast.add('Failed to load API keys', 'error')
  } finally {
    loadingKeys.value = false
  }
}

async function createKey() {
  if (!newKeyName.value.trim()) return
  creatingKey.value = true
  try {
    const created = await apiFetch('/api-keys', {
      method: 'POST',
      body: JSON.stringify({ name: newKeyName.value.trim() }),
    })
    newTokenValue.value = created.token
    showNewKeyForm.value = false
    newKeyName.value = ''
    await loadKeys()
  } catch {
    toast.add('Failed to create API key', 'error')
  } finally {
    creatingKey.value = false
  }
}

async function revokeKey(key) {
  if (!confirm(`Revoke "${key.name}"? Any systems using it will lose access.`)) return
  revokingKey.value = key.id
  try {
    await apiFetch(`/api-keys/${key.id}`, { method: 'DELETE' })
    toast.add(`"${key.name}" revoked`, 'success')
    await loadKeys()
  } catch {
    toast.add('Failed to revoke key', 'error')
  } finally {
    revokingKey.value = null
  }
}

async function copyToken() {
  try {
    await navigator.clipboard.writeText(newTokenValue.value)
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  } catch {
    toast.add('Could not copy to clipboard', 'error')
  }
}

loadKeys()

const flagDefs = [
  {
    key: 'playlists',
    label: 'Playlists',
    description: 'Show the Playlists section on kiosk detail pages and the Playlists nav item.',
  },
  {
    key: 'debug',
    label: 'Debug',
    description: 'Show debug page links on kiosk detail pages.',
  },
]

async function toggle(key) {
  saving.value = key
  try {
    await flagStore.set(key, !flagStore.isEnabled(key))
    toast.add(`${key} ${flagStore.isEnabled(key) ? 'enabled' : 'disabled'}`, 'success')
  } catch {
    toast.add('Failed to update feature flag', 'error')
  } finally {
    saving.value = null
  }
}

// --- Agents settings ---
const agentFields = [
  { key: 'heartbeat_interval_seconds', label: 'Heartbeat interval', description: 'How often nodes report status.', unit: 'sec', min: 5, max: 3600 },
  { key: 'heartbeat_jitter_seconds', label: 'Heartbeat jitter', description: 'Random spread added per node so they don\'t all check in at once.', unit: 'sec', min: 0, max: 300 },
  { key: 'metadata_interval_seconds', label: 'Metadata heartbeat interval', description: 'How often nodes send full metadata (display, inputs, IP).', unit: 'sec', min: 60, max: 86400 },
  { key: 'settings_checkin_seconds', label: 'Settings checkin', description: 'How often nodes re-fetch these settings.', unit: 'sec', min: 30, max: 86400 },
  { key: 'node_offline_threshold_seconds', label: 'Node health timeout', description: 'A node with no heartbeat for this long is marked offline.', unit: 'sec', min: 10, max: 3600 },
  { key: 'event_log_purge_days', label: 'Event log retention', description: 'Event-log entries older than this are purged.', unit: 'days', min: 1, max: 365 },
]

const agentSettings = ref({})
const loadingAgents = ref(true)
const savingAgents = ref(false)

async function loadAgents() {
  try {
    agentSettings.value = await apiFetch('/settings/agent')
  } catch {
    toast.add('Failed to load agent settings', 'error')
  } finally {
    loadingAgents.value = false
  }
}

async function saveAgents() {
  savingAgents.value = true
  try {
    const payload = {}
    for (const f of agentFields) payload[f.key] = Number(agentSettings.value[f.key])
    agentSettings.value = await apiFetch('/settings/agent', {
      method: 'PUT',
      body: JSON.stringify(payload),
    })
    toast.add('Agent settings saved', 'success')
  } catch (e) {
    toast.add(e.status === 422 ? 'Invalid value — check the ranges' : 'Failed to save agent settings', 'error')
  } finally {
    savingAgents.value = false
  }
}

loadAgents()
</script>
