<template>
  <div>
    <div class="page-header">
      <div>
        <RouterLink to="/settings" class="text-muted text-sm" style="display: inline-flex; align-items: center; gap: 4px; margin-bottom: 0.4rem">
          ← Settings
        </RouterLink>
        <h1 class="page-title">Default Page</h1>
      </div>
      <button class="btn btn-primary" style="min-width: 64px" :disabled="saving || loading" @click="save">
        {{ saving ? 'Saving…' : 'Save' }}
      </button>
    </div>

    <div class="card" style="max-width: 560px">
      <p class="text-xs text-muted" style="margin-bottom: 1.25rem">
        The page every node shows when it has nothing else to do — on boot with no playlist running,
        and when the last open tab is closed. Leave it blank to fall back to each node's own start page.
        Changes apply the next time a node is idle.
      </p>
      <div v-if="loading" class="text-muted text-sm">Loading…</div>
      <div v-else>
        <label class="form-label">Default URL</label>
        <input
          v-model="url"
          type="url"
          class="form-input"
          placeholder="https://dashboard.example.local"
          style="font-family: monospace; font-size: 0.85rem"
          @keyup.enter="save"
        />
        <p v-if="error" class="text-xs" style="color: var(--danger, #e5484d); margin-top: 0.5rem">{{ error }}</p>
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
const url = ref('')
const error = ref('')

function validate(value) {
  if (!value) return ''  // empty clears the default
  if (!/^(https?:\/\/|about:)/.test(value)) {
    return 'URL must start with http://, https://, or about:'
  }
  return ''
}

async function load() {
  try {
    const data = await apiFetch('/settings/node/default-url')
    url.value = data.url || ''
  } catch {
    toast.add('Failed to load default page', 'error')
  } finally {
    loading.value = false
  }
}

async function save() {
  const trimmed = url.value.trim()
  error.value = validate(trimmed)
  if (error.value) return
  saving.value = true
  try {
    await apiFetch('/settings/node/default-url', {
      method: 'PUT',
      body: JSON.stringify({ url: trimmed }),
    })
    url.value = trimmed
    toast.add('Default page saved', 'success')
  } catch {
    toast.add('Failed to save default page', 'error')
  } finally {
    saving.value = false
  }
}

load()
</script>
