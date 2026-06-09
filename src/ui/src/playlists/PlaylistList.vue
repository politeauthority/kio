<template>
  <div>
    <div class="page-header">
      <div>
        <h1 class="page-title">Playlists</h1>
        <p class="page-subtitle">Collections of URLs that cycle on a kiosk</p>
      </div>
      <button class="btn btn-primary" @click="openCreate">+ New Playlist</button>
    </div>

    <div v-if="loading" class="text-muted text-sm">Loading…</div>

    <div v-else-if="playlists.length === 0" class="empty-state">
      No playlists yet — create one to get started.
    </div>

    <div v-else class="card" style="padding: 0; overflow: hidden">
      <table class="table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Items</th>
            <th>Created</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="pl in playlists"
            :key="pl.id"
            style="cursor: pointer"
            @click="router.push(`/playlists/${pl.id}`)"
          >
            <td style="font-weight: 500">{{ pl.name }}</td>
            <td class="text-muted text-sm">{{ pl.item_count ?? '—' }} URLs</td>
            <td class="text-muted text-sm">{{ formatDate(pl.created_at) }}</td>
            <td style="text-align: right; width: 60px">
              <button
                class="btn btn-ghost text-sm"
                style="color: var(--danger)"
                @click.stop="confirmDelete(pl)"
              >Delete</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Create dialog -->
    <div v-if="showCreate" class="dialog-backdrop" @click.self="showCreate = false">
      <div class="dialog">
        <h2 class="dialog-title">New Playlist</h2>
        <form @submit.prevent="create">
          <div>
            <label class="form-label">Name</label>
            <input
              v-model="form.name"
              class="form-input"
              placeholder="Morning Loop"
              required
              autofocus
            />
          </div>
          <div class="mt-md">
            <label class="form-label">Description <span class="text-muted">(optional)</span></label>
            <input v-model="form.description" class="form-input" placeholder="Runs 9am–12pm in the lobby" />
          </div>
          <div class="dialog-actions">
            <button type="button" class="btn btn-secondary" @click="showCreate = false">Cancel</button>
            <button type="submit" class="btn btn-primary" :disabled="saving">
              {{ saving ? 'Creating…' : 'Create' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- Delete confirm dialog -->
    <div v-if="deleteTarget" class="dialog-backdrop" @click.self="deleteTarget = null">
      <div class="dialog">
        <h2 class="dialog-title">Delete "{{ deleteTarget.name }}"?</h2>
        <p class="text-secondary text-sm">This will remove the playlist and unassign it from any kiosk currently using it.</p>
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
import { useRouter } from 'vue-router'
import { useApi } from '../composables/useApi'
import { useToastStore } from '../stores/toast'

const router = useRouter()
const { apiFetch } = useApi()
const toast = useToastStore()

const playlists = ref([])
const loading = ref(true)
const showCreate = ref(false)
const saving = ref(false)
const deleting = ref(false)
const deleteTarget = ref(null)
const form = ref({ name: '', description: '' })

async function load() {
  try {
    playlists.value = await apiFetch('/playlists')
  } catch {
    toast.add('Failed to load playlists', 'error')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.value = { name: '', description: '' }
  showCreate.value = true
}

async function create() {
  saving.value = true
  try {
    const pl = await apiFetch('/playlists', {
      method: 'POST',
      body: JSON.stringify(form.value),
    })
    showCreate.value = false
    router.push(`/playlists/${pl.id}`)
  } catch {
    toast.add('Failed to create playlist', 'error')
  } finally {
    saving.value = false
  }
}

function confirmDelete(pl) {
  deleteTarget.value = pl
}

async function doDelete() {
  deleting.value = true
  try {
    await apiFetch(`/playlists/${deleteTarget.value.id}`, { method: 'DELETE' })
    playlists.value = playlists.value.filter(p => p.id !== deleteTarget.value.id)
    toast.add(`"${deleteTarget.value.name}" deleted`, 'success')
    deleteTarget.value = null
  } catch {
    toast.add('Failed to delete playlist', 'error')
  } finally {
    deleting.value = false
  }
}

function formatDate(ts) {
  if (!ts) return '—'
  return new Date(ts).toLocaleDateString()
}

onMounted(load)
</script>
