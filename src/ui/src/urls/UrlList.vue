<template>
  <div>
    <div class="page-header">
      <div>
        <h1 class="page-title">Saved URLs</h1>
        <p class="page-subtitle">Predefined URLs for quick navigation and playlists</p>
      </div>
      <button class="btn btn-primary" @click="openCreate">+ New URL</button>
    </div>

    <div v-if="loading" class="text-muted text-sm">Loading…</div>

    <div v-else-if="urls.length === 0" class="empty-state">
      No saved URLs yet — add one to use as a quick-pick in kiosk navigation and playlists.
    </div>

    <div v-else class="card" style="padding: 0; overflow: hidden">
      <table class="table">
        <thead>
          <tr>
            <th>Name</th>
            <th>URL</th>
            <th>Description</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in urls" :key="u.id">
            <td style="font-weight: 500; white-space: nowrap">{{ u.name }}</td>
            <td class="text-muted text-sm" style="max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
              <a :href="u.url" target="_blank" rel="noopener noreferrer" style="color: var(--accent)" @click.stop>{{ u.url }}</a>
            </td>
            <td class="text-muted text-sm">{{ u.description || '—' }}</td>
            <td style="text-align: right; white-space: nowrap; width: 120px">
              <RouterLink :to="`/urls/${u.id}/edit`" class="btn btn-ghost text-sm">Edit</RouterLink>
              <button class="btn btn-ghost text-sm" style="color: var(--danger)" @click="confirmDelete(u)">Delete</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Create dialog -->
    <div v-if="showForm" class="dialog-backdrop" @click.self="showForm = false">
      <div class="dialog">
        <h2 class="dialog-title">New URL</h2>
        <form @submit.prevent="create">
          <div>
            <label class="form-label">Name</label>
            <input v-model="form.name" class="form-input" placeholder="Dashboard" required autofocus />
          </div>
          <div class="mt-md">
            <label class="form-label">URL</label>
            <input v-model="form.url" class="form-input" placeholder="https://example.com" type="url" required />
          </div>
          <div class="mt-md">
            <label class="form-label">Description <span class="text-muted">(optional)</span></label>
            <input v-model="form.description" class="form-input" placeholder="Main lobby display" />
          </div>
          <div class="dialog-actions">
            <button type="button" class="btn btn-secondary" @click="showForm = false">Cancel</button>
            <button type="submit" class="btn btn-primary" :disabled="saving">
              {{ saving ? 'Saving…' : 'Create' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- Delete confirm dialog -->
    <div v-if="deleteTarget" class="dialog-backdrop" @click.self="deleteTarget = null">
      <div class="dialog">
        <h2 class="dialog-title">Delete "{{ deleteTarget.name }}"?</h2>
        <p class="text-secondary text-sm">This URL will no longer appear as a suggestion.</p>
        <div class="dialog-actions">
          <button class="btn btn-secondary" @click="deleteTarget = null">Cancel</button>
          <button class="btn btn-danger" :disabled="deleting" @click="doDelete">
            {{ deleting ? 'Deleting…' : 'Delete' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import { useApi } from '../composables/useApi'
import { useToastStore } from '../stores/toast'

const { apiFetch } = useApi()
const toast = useToastStore()

const urls = ref([])
const loading = ref(true)
const showForm = ref(false)
const saving = ref(false)
const deleting = ref(false)
const deleteTarget = ref(null)
const form = ref({ name: '', url: '', description: '' })

async function load() {
  try {
    urls.value = await apiFetch('/saved-urls')
  } catch {
    toast.add('Failed to load saved URLs', 'error')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.value = { name: '', url: '', description: '' }
  showForm.value = true
}

async function create() {
  saving.value = true
  try {
    const created = await apiFetch('/saved-urls', {
      method: 'POST',
      body: JSON.stringify(form.value),
    })
    urls.value = [created, ...urls.value]
    toast.add('URL created', 'success')
    showForm.value = false
  } catch {
    toast.add('Failed to create URL', 'error')
  } finally {
    saving.value = false
  }
}

function confirmDelete(u) {
  deleteTarget.value = u
}

async function doDelete() {
  deleting.value = true
  try {
    await apiFetch(`/saved-urls/${deleteTarget.value.id}`, { method: 'DELETE' })
    urls.value = urls.value.filter(u => u.id !== deleteTarget.value.id)
    toast.add(`"${deleteTarget.value.name}" deleted`, 'success')
    deleteTarget.value = null
  } catch {
    toast.add('Failed to delete URL', 'error')
  } finally {
    deleting.value = false
  }
}

onMounted(load)
</script>
