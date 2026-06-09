<template>
  <div v-if="url">
    <div class="page-header">
      <div>
        <RouterLink to="/urls" class="text-muted text-sm" style="display: inline-flex; align-items: center; gap: 4px; margin-bottom: 0.4rem">
          ← Saved URLs
        </RouterLink>
        <h1 class="page-title">Edit URL</h1>
      </div>
      <button class="btn btn-primary" :disabled="saving" @click="save">
        {{ saving ? 'Saving…' : 'Save' }}
      </button>
    </div>

    <div class="card">
      <div class="card-header">Details</div>
      <div style="display: flex; flex-direction: column; gap: var(--space-md); max-width: 480px">
        <div>
          <label class="form-label">Name</label>
          <input v-model="form.name" class="form-input" required />
        </div>
        <div>
          <label class="form-label">URL</label>
          <input v-model="form.url" class="form-input" type="url" required />
        </div>
        <div>
          <label class="form-label">Description <span class="text-muted">(optional)</span></label>
          <input v-model="form.description" class="form-input" placeholder="Main lobby display" />
        </div>
      </div>
    </div>

    <div class="card mt-lg" style="border-color: color-mix(in srgb, var(--danger) 30%, var(--border))">
      <div class="card-header" style="color: var(--danger)">Danger Zone</div>
      <div style="display: flex; align-items: center; justify-content: space-between">
        <div>
          <div class="text-sm" style="font-weight: 500">Delete this URL</div>
          <div class="text-xs text-muted mt-sm">Removes it from suggestions and playlists. This cannot be undone.</div>
        </div>
        <button class="btn btn-danger" @click="deleteUrl">Delete URL</button>
      </div>
    </div>
  </div>

  <div v-else-if="loading" class="text-muted text-sm">Loading…</div>
  <div v-else class="empty-state">URL not found.</div>
</template>

<script setup>
import { ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { useApi } from '../composables/useApi'
import { useToastStore } from '../stores/toast'

const route = useRoute()
const router = useRouter()
const { apiFetch } = useApi()
const toast = useToastStore()

const urlId = route.params.id
const url = ref(null)
const loading = ref(true)
const saving = ref(false)
const form = ref({ name: '', url: '', description: '' })

async function load() {
  try {
    const data = await apiFetch(`/saved-urls/${urlId}`)
    url.value = data
    form.value = { name: data.name, url: data.url, description: data.description || '' }
  } catch {
    toast.add('Failed to load URL', 'error')
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    await apiFetch(`/saved-urls/${urlId}`, {
      method: 'PUT',
      body: JSON.stringify(form.value),
    })
    toast.add('URL saved', 'success')
    router.push('/urls')
  } catch {
    toast.add('Failed to save URL', 'error')
  } finally {
    saving.value = false
  }
}

async function deleteUrl() {
  if (!confirm(`Delete "${url.value.name}"? This cannot be undone.`)) return
  try {
    await apiFetch(`/saved-urls/${urlId}`, { method: 'DELETE' })
    toast.add(`"${url.value.name}" deleted`, 'success')
    router.push('/urls')
  } catch {
    toast.add('Failed to delete URL', 'error')
  }
}

load()
</script>
