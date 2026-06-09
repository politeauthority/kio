<template>
  <div>
    <div class="page-header">
      <div>
        <RouterLink to="/settings" class="text-muted text-sm" style="display: inline-flex; align-items: center; gap: 4px; margin-bottom: 0.4rem">
          ← Settings
        </RouterLink>
        <h1 class="page-title">API Keys</h1>
      </div>
      <button class="btn btn-primary" @click="showCreate = true">+ New Key</button>
    </div>

    <div class="card">
      <div v-if="loading" class="text-muted text-sm">Loading…</div>
      <div v-else-if="keys.length === 0" class="text-muted text-sm" style="padding: 0.5rem 0">
        No API keys yet.
      </div>
      <table v-else class="table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Prefix</th>
            <th>Status</th>
            <th>Created</th>
            <th>Last Used</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="key in keys" :key="key.id">
            <td class="text-sm" style="font-weight: 500">{{ key.name }}</td>
            <td>
              <code style="font-size: 0.8rem; color: var(--text-muted)">{{ key.key_prefix }}…</code>
            </td>
            <td>
              <span
                class="text-xs"
                style="padding: 0.2rem 0.5rem; border-radius: 999px; font-weight: 500"
                :style="key.is_active
                  ? 'background: color-mix(in srgb, var(--success) 15%, transparent); color: var(--success)'
                  : 'background: color-mix(in srgb, var(--text-muted) 15%, transparent); color: var(--text-muted)'"
              >
                {{ key.is_active ? 'Active' : 'Revoked' }}
              </span>
            </td>
            <td class="text-sm text-muted">{{ formatDate(key.created_at) }}</td>
            <td class="text-sm text-muted">{{ key.last_used_at ? formatDate(key.last_used_at) : 'never' }}</td>
            <td style="display: flex; gap: 0.5rem; justify-content: flex-end">
              <button
                v-if="key.is_active"
                class="btn btn-ghost text-sm"
                style="color: var(--danger); padding: 0.2rem 0.5rem"
                @click="revoke(key)"
              >
                Revoke
              </button>
              <button
                class="btn btn-ghost text-sm"
                style="padding: 0.2rem 0.5rem; color: var(--danger)"
                @click="deleteKey(key)"
              >
                Delete
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Create key dialog -->
    <div v-if="showCreate" class="dialog-backdrop" @click.self="showCreate = false">
      <div class="dialog">
        <h2 class="dialog-title">New API Key</h2>
        <form @submit.prevent="createKey">
          <div class="mt-md">
            <label class="form-label">Name</label>
            <input v-model="createForm.name" class="form-input" placeholder="e.g. Home Assistant" autofocus required />
          </div>
          <div class="dialog-actions">
            <button type="button" class="btn btn-secondary" @click="showCreate = false">Cancel</button>
            <button type="submit" class="btn btn-primary" :disabled="creating">
              {{ creating ? 'Creating…' : 'Create' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- Show new key dialog -->
    <div v-if="newKeyValue" class="dialog-backdrop">
      <div class="dialog">
        <h2 class="dialog-title">API Key Created</h2>
        <p class="text-sm text-muted" style="margin-bottom: 1rem">Copy this key now — it won't be shown again.</p>
        <div style="background: var(--bg-dark); border: 1px solid var(--border); border-radius: var(--radius); padding: 0.75rem 1rem; font-family: monospace; font-size: 0.82rem; word-break: break-all; color: var(--text-primary); user-select: all">
          {{ newKeyValue }}
        </div>
        <div class="dialog-actions">
          <button class="btn btn-secondary" @click="copyKey">Copy</button>
          <button class="btn btn-primary" @click="newKeyValue = null">Done</button>
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
const keys = ref([])
const showCreate = ref(false)
const creating = ref(false)
const createForm = ref({ name: '' })
const newKeyValue = ref(null)

function formatDate(ts) {
  return new Date(ts).toLocaleString()
}

async function load() {
  try {
    keys.value = await apiFetch('/settings/api-keys')
  } catch {
    toast.add('Failed to load API keys', 'error')
  } finally {
    loading.value = false
  }
}

async function createKey() {
  creating.value = true
  try {
    const created = await apiFetch('/settings/api-keys', {
      method: 'POST',
      body: JSON.stringify({ name: createForm.value.name }),
    })
    newKeyValue.value = created.key
    showCreate.value = false
    createForm.value = { name: '' }
    await load()
  } catch {
    toast.add('Failed to create API key', 'error')
  } finally {
    creating.value = false
  }
}

async function revoke(key) {
  if (!confirm(`Revoke "${key.name}"? It will stop working immediately.`)) return
  try {
    await apiFetch(`/settings/api-keys/${key.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ is_active: false }),
    })
    toast.add('Key revoked', 'success')
    await load()
  } catch {
    toast.add('Failed to revoke key', 'error')
  }
}

async function deleteKey(key) {
  if (!confirm(`Delete "${key.name}"? This cannot be undone.`)) return
  try {
    await apiFetch(`/settings/api-keys/${key.id}`, { method: 'DELETE' })
    toast.add('Key deleted', 'success')
    keys.value = keys.value.filter(k => k.id !== key.id)
  } catch {
    toast.add('Failed to delete key', 'error')
  }
}

async function copyKey() {
  try {
    await navigator.clipboard.writeText(newKeyValue.value)
    toast.add('Key copied', 'success')
  } catch {
    toast.add('Copy failed — select and copy manually', 'error')
  }
}

load()
</script>
