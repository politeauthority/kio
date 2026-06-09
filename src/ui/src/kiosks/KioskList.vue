<template>
  <div>
    <div class="page-header">
      <div>
        <h1 class="page-title">Kiosks</h1>
      </div>
      <button class="btn btn-primary" @click="showAddModal = true">+ Add Kiosk</button>
    </div>

    <div v-if="loading" class="text-muted text-sm">Loading…</div>

    <div v-else-if="kiosks.length === 0" class="empty-state">
      No kiosks yet — add one to get started.
    </div>

    <div v-else class="card" style="padding: 0; overflow: hidden">
      <table class="table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Status</th>
            <th>Hostname</th>
            <th>Current URL</th>
            <th>Last Seen</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="kiosk in kiosks"
            :key="kiosk.id"
            style="cursor: pointer"
            @click="router.push(`/kiosks/${kiosk.id}`)"
          >
            <td class="text-sm" style="font-weight: 500">{{ kiosk.name }}</td>
            <td>
              <span class="status-badge" :class="`status-${kiosk.status}`">
                {{ kiosk.status }}
              </span>
            </td>
            <td><code>{{ kiosk.hostname }}</code></td>
            <td style="max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
              <a
                v-if="kiosk.current_url"
                :href="kiosk.current_url"
                target="_blank"
                rel="noopener"
                class="text-sm text-muted"
                @click.stop
              >{{ kiosk.current_url }}</a>
              <span v-else class="text-muted">—</span>
            </td>
            <td class="text-muted text-sm">{{ formatLastSeen(kiosk.last_seen) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Add Kiosk Modal -->
    <div v-if="showAddModal" class="dialog-backdrop" @click.self="showAddModal = false">
      <div class="dialog">
        <h2 class="dialog-title">Add Kiosk</h2>
        <form @submit.prevent="createKiosk">
          <div class="mt-md">
            <label class="form-label">Name</label>
            <input v-model="form.name" class="form-input" placeholder="Lobby Display" required />
          </div>
          <div class="mt-md">
            <label class="form-label">Hostname</label>
            <input v-model="form.hostname" class="form-input" placeholder="kio-1" required />
          </div>
          <div class="dialog-actions">
            <button type="button" class="btn btn-secondary" @click="showAddModal = false">Cancel</button>
            <button type="submit" class="btn btn-primary" :disabled="saving">
              {{ saving ? 'Adding…' : 'Add Kiosk' }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
import { useApi } from '../composables/useApi'
import { useToastStore } from '../stores/toast'

const { apiFetch } = useApi()
const toast = useToastStore()

const kiosks = ref([])
const loading = ref(true)
const showAddModal = ref(false)
const saving = ref(false)
const form = ref({ name: '', hostname: '' })

let pollInterval = null

async function load(showError = false) {
  try {
    kiosks.value = await apiFetch('/kiosks')
  } catch {
    if (showError) toast.add('Failed to load kiosks', 'error')
  } finally {
    loading.value = false
  }
}

async function createKiosk() {
  saving.value = true
  try {
    const kiosk = await apiFetch('/kiosks', {
      method: 'POST',
      body: JSON.stringify(form.value),
    })
    kiosks.value.push(kiosk)
    showAddModal.value = false
    form.value = { name: '', hostname: '' }
    toast.add(`${kiosk.name} added`, 'success')
  } catch {
    toast.add('Failed to add kiosk', 'error')
  } finally {
    saving.value = false
  }
}

function formatLastSeen(ts) {
  if (!ts) return 'never'
  const d = new Date(ts)
  return d.toLocaleTimeString()
}

onMounted(() => {
  load(true)
  pollInterval = setInterval(load, 10_000)
})

onUnmounted(() => clearInterval(pollInterval))
</script>
