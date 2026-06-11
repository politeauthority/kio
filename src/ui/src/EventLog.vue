<template>
  <div>
    <div class="page-header">
      <h1 class="page-title">Event Log</h1>
    </div>

    <div class="card">
      <!-- Filters -->
      <div style="display: flex; flex-wrap: wrap; gap: 0.75rem; margin-bottom: 1rem">
        <select v-model="kioskId" class="form-input" style="max-width: 220px">
          <option value="">All kiosks</option>
          <option v-for="k in kiosks" :key="k.id" :value="k.id">{{ k.name }}</option>
        </select>

        <select v-model="command" class="form-input" style="max-width: 220px">
          <option value="">All event types</option>
          <option v-for="c in commands" :key="c" :value="c">{{ c }}</option>
        </select>

        <select v-model="status" class="form-input" style="max-width: 180px">
          <option value="">All statuses</option>
          <option value="ok">OK</option>
          <option value="failed">Failed</option>
          <option value="pending">Pending</option>
          <option value="no_response">No response</option>
        </select>

        <input
          v-model="searchInput"
          class="form-input"
          type="search"
          placeholder="Search command or message…"
          style="max-width: 280px"
        />
      </div>

      <div v-if="loading" class="text-muted text-sm">Loading…</div>

      <template v-else>
        <div v-if="rows.length === 0" class="text-muted text-sm">No events found.</div>
        <table v-else class="table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Kiosk</th>
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
                <td class="text-sm">
                  <RouterLink :to="`/kiosks/${entry.kiosk_id}/log`" @click.stop>{{ entry.kiosk_name }}</RouterLink>
                </td>
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
                <td colspan="6"><pre class="msg-detail" :class="{ 'is-error': entry.status === 'failed' }">{{ entry.agent_message }}</pre></td>
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
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import { useApi } from './composables/useApi'
import { useToastStore } from './stores/toast'

const { apiFetch } = useApi()
const toast = useToastStore()

const PAGE_SIZE = 20

const rows = ref([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)

const kiosks = ref([])
const commands = ref([])

const kioskId = ref('')
const command = ref('')
const status = ref('')

// Event rows whose error detail is currently expanded.
const expandedRows = ref(new Set())
function toggleRow(id) {
  const next = new Set(expandedRows.value)
  next.has(id) ? next.delete(id) : next.add(id)
  expandedRows.value = next
}
const searchInput = ref('')
const search = ref('')

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))

let debounceTimer = null
watch(searchInput, val => {
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    search.value = val
  }, 300)
})

// Any filter change resets to the first page.
watch([kioskId, command, status, search], () => {
  page.value = 1
})

watch([page, kioskId, command, status, search], fetchLog)

async function fetchLog() {
  loading.value = true
  try {
    const params = new URLSearchParams({
      limit: PAGE_SIZE,
      offset: (page.value - 1) * PAGE_SIZE,
    })
    if (kioskId.value) params.set('kiosk_id', kioskId.value)
    if (command.value) params.set('command', command.value)
    if (status.value) params.set('status', status.value)
    if (search.value) params.set('search', search.value)

    const res = await apiFetch(`/event-logs?${params}`, { raw: true })
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
    kiosks.value = await apiFetch('/kiosks')
  } catch {
    // leave empty — filter just shows "All kiosks"
  }
  try {
    commands.value = await apiFetch('/event-logs/commands')
  } catch {
    // leave empty — filter just shows "All event types"
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
