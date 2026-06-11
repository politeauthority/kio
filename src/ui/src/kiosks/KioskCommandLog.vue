<template>
  <div v-if="kiosk">
    <div class="page-header">
      <div>
        <RouterLink :to="`/kiosks/${kioskId}`" class="text-muted text-sm">← {{ kiosk.name }}</RouterLink>
        <h1 class="page-title mt-sm">Event Log</h1>
      </div>
    </div>

    <div class="card">
      <!-- Search -->
      <div style="margin-bottom: 1rem">
        <input
          v-model="searchInput"
          class="form-input"
          type="search"
          placeholder="Search commands…"
          style="max-width: 320px"
        />
      </div>

      <div v-if="loading" class="text-muted text-sm">Loading…</div>

      <template v-else>
        <div v-if="rows.length === 0" class="text-muted text-sm">No events found.</div>
        <table v-else class="table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Command</th>
              <th>Subject</th>
              <th>Source</th>
              <th>Result</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="entry in rows" :key="entry.id">
              <tr
                :class="{ 'row-expandable': !!entry.agent_message }"
                @click="entry.agent_message && toggleRow(entry.id)"
              >
                <td class="text-xs text-muted" style="white-space: nowrap">{{ formatDate(entry.sent_at) }}</td>
                <td class="text-sm"><code>{{ entry.command }}</code></td>
                <td class="text-xs text-muted" style="word-break: break-all">{{ entry.subject ?? '—' }}</td>
                <td class="text-xs text-muted">{{ entry.source }}</td>
                <td>
                  <span class="result-cell">
                    <span v-if="entry.status === 'ok'" class="result-ok">✓</span>
                    <span v-else-if="entry.status === 'failed'" class="result-fail">✗</span>
                    <span v-else-if="entry.status === 'no_response'" style="color: var(--warning); font-size: 0.75rem">no response</span>
                    <span v-else class="text-muted text-xs">pending</span>
                    <span v-if="entry.agent_message" class="expand-caret">{{ expandedRows.has(entry.id) ? '▲' : '▼' }}</span>
                  </span>
                </td>
              </tr>
              <tr v-if="entry.agent_message && expandedRows.has(entry.id)" class="msg-detail-row">
                <td colspan="5"><pre class="msg-detail" :class="{ 'is-error': entry.status === 'failed' }">{{ entry.agent_message }}</pre></td>
              </tr>
            </template>
          </tbody>
        </table>

        <!-- Pagination -->
        <div v-if="totalPages > 1" style="display: flex; align-items: center; gap: 0.75rem; margin-top: 1rem">
          <button class="btn btn-secondary" :disabled="page === 1" @click="page--">← Prev</button>
          <span class="text-sm text-muted">Page {{ page }} of {{ totalPages }}</span>
          <button class="btn btn-secondary" :disabled="page === totalPages" @click="page++">Next →</button>
          <span class="text-xs text-muted" style="margin-left: auto">{{ total }} total</span>
        </div>
      </template>
    </div>
  </div>

  <div v-else-if="loadingKiosk" class="text-muted text-sm">Loading…</div>
  <div v-else class="empty-state">Kiosk not found.</div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { useApi } from '../composables/useApi'
import { useToastStore } from '../stores/toast'

const { apiFetch } = useApi()
const toast = useToastStore()
const route = useRoute()

const PAGE_SIZE = 20

const kiosk = ref(null)
const loadingKiosk = ref(true)
const rows = ref([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const searchInput = ref('')
const search = ref('')

// Event rows whose error detail is currently expanded.
const expandedRows = ref(new Set())
function toggleRow(id) {
  const next = new Set(expandedRows.value)
  next.has(id) ? next.delete(id) : next.add(id)
  expandedRows.value = next
}

const kioskId = computed(() => route.params.id)
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))

let debounceTimer = null

watch(searchInput, val => {
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    search.value = val
    page.value = 1
  }, 300)
})

watch([page, search], fetchLog)

async function fetchLog() {
  loading.value = true
  try {
    const params = new URLSearchParams({
      limit: PAGE_SIZE,
      offset: (page.value - 1) * PAGE_SIZE,
    })
    if (search.value) params.set('search', search.value)

    const res = await apiFetch(`/kiosks/${kioskId.value}/command-log?${params}`, { raw: true })
    total.value = parseInt(res.headers.get('X-Total-Count') ?? '0', 10)
    rows.value = await res.json()
  } catch {
    toast.add('Failed to load event log', 'error')
  } finally {
    loading.value = false
  }
}

function formatDate(ts) {
  return new Date(ts).toLocaleString()
}

onMounted(async () => {
  try {
    kiosk.value = await apiFetch(`/kiosks/${kioskId.value}`)
  } catch {
    // leave kiosk null — shows not found
  } finally {
    loadingKiosk.value = false
  }
  fetchLog()
})
</script>

<style scoped>
.row-expandable {
  cursor: pointer;
}
.row-expandable:hover td {
  background: rgba(255, 255, 255, 0.03);
}

.result-cell {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
}
.result-ok {
  color: var(--success);
  font-size: 0.85rem;
  font-weight: 600;
}
.result-fail {
  color: var(--danger);
  font-size: 0.8rem;
}
.expand-caret {
  font-size: 0.7rem;
  color: var(--text-muted);
}

.msg-detail-row td {
  padding: 0;
}
.msg-detail {
  margin: 0;
  padding: 0.6rem 0.85rem;
  background: rgba(255, 255, 255, 0.03);
  border-left: 2px solid var(--border);
  color: var(--text-muted);
  font-size: 0.75rem;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.msg-detail.is-error {
  background: rgba(239, 68, 68, 0.08);
  border-left-color: var(--danger);
  color: var(--danger);
}
</style>
