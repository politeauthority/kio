<template>
  <div>
    <div class="page-header">
      <div>
        <RouterLink to="/settings" class="text-muted text-sm" style="display: inline-flex; align-items: center; gap: 4px; margin-bottom: 0.4rem">
          ← Settings
        </RouterLink>
        <h1 class="page-title">Certificates</h1>
      </div>
      <button
        class="btn btn-secondary"
        :disabled="syncing || certs.length === 0"
        @click="syncAll"
      >
        {{ syncing ? 'Syncing…' : 'Sync All to Kiosks' }}
      </button>
    </div>

    <!-- Info / guide -->
    <div class="card" style="max-width: 680px; margin-bottom: var(--space-lg)">
      <p class="text-sm text-muted" style="margin-bottom: 0.75rem">
        CA certificates uploaded here are installed on every kio node, allowing Chromium to load
        internal HTTPS services that use self-signed certificates (e.g. Grafana, Home Assistant, or
        other LAN dashboards). Certificates are synced automatically on agent restart and on demand
        via <strong>Sync All to Kiosks</strong>.
      </p>
      <details>
        <summary class="text-sm" style="cursor: pointer; color: var(--accent); user-select: none">
          How to export a certificate from a URL
        </summary>
        <div style="margin-top: 0.75rem; display: flex; flex-direction: column; gap: 0.75rem">
          <p class="text-xs text-muted">Run this on any machine that can reach the internal service:</p>
          <pre style="background: var(--bg-dark); border: 1px solid var(--border); border-radius: var(--radius); padding: 0.75rem; font-size: 0.78rem; overflow-x: auto; white-space: pre-wrap; word-break: break-all">echo | openssl s_client -connect &lt;host&gt;:443 -servername &lt;host&gt; 2>/dev/null | openssl x509 -outform PEM</pre>
          <p class="text-xs text-muted">
            Or in your browser: click the padlock → <em>Certificate</em> → export as PEM.
            The PEM content starts with <code>-----BEGIN CERTIFICATE-----</code>.
          </p>
        </div>
      </details>
    </div>

    <!-- Add cert form -->
    <div class="card" style="max-width: 680px; margin-bottom: var(--space-lg)">
      <h2 class="text-sm" style="font-weight: 600; margin-bottom: var(--space-md)">Add Certificate</h2>
      <form @submit.prevent="addCert">
        <div style="margin-bottom: var(--space-md)">
          <label class="form-label">Name</label>
          <input
            v-model="form.name"
            class="form-input"
            placeholder="e.g. grafana-colfax-int"
            required
          />
        </div>
        <div style="margin-bottom: var(--space-md)">
          <label class="form-label">Description <span class="text-muted">(optional)</span></label>
          <input
            v-model="form.description"
            class="form-input"
            placeholder="e.g. Self-signed CA for internal Grafana"
          />
        </div>
        <div style="margin-bottom: var(--space-md)">
          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.35rem">
            <label class="form-label" style="margin: 0">PEM Content</label>
            <label
              class="btn btn-ghost text-xs"
              style="cursor: pointer; padding: 0.2rem 0.5rem"
              title="Load from file"
            >
              Load file
              <input type="file" accept=".pem,.crt,.cer" style="display: none" @change="loadFile" />
            </label>
          </div>
          <textarea
            v-model="form.content"
            class="form-input"
            :class="pemError ? 'form-input-error' : ''"
            rows="8"
            placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"
            style="resize: vertical; font-family: monospace; font-size: 0.8rem; line-height: 1.6"
            @input="validatePem"
            required
          />
          <div v-if="pemError" style="color: var(--danger); font-size: 0.8rem; margin-top: 0.35rem">{{ pemError }}</div>
        </div>
        <button type="submit" class="btn btn-primary" :disabled="adding || !!pemError">
          {{ adding ? 'Adding…' : 'Add Certificate' }}
        </button>
      </form>
    </div>

    <!-- Cert list -->
    <div class="card" style="max-width: 680px">
      <h2 class="text-sm" style="font-weight: 600; margin-bottom: var(--space-md)">Installed Certificates</h2>
      <div v-if="loading" class="text-muted text-sm">Loading…</div>
      <div v-else-if="certs.length === 0" class="text-muted text-sm" style="padding: 0.5rem 0">
        No certificates uploaded yet.
      </div>
      <div v-else style="display: flex; flex-direction: column; gap: var(--space-sm)">
        <div
          v-for="cert in certs"
          :key="cert.id"
          style="display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-md); padding: var(--space-md); border: 1px solid var(--border); border-radius: var(--radius)"
        >
          <div style="min-width: 0">
            <div style="font-weight: 500; font-size: 0.9rem">{{ cert.name }}</div>
            <div v-if="cert.description" class="text-xs text-muted" style="margin-top: 0.15rem">{{ cert.description }}</div>
            <div class="text-xs text-muted" style="margin-top: 0.25rem">Added {{ formatDate(cert.created_at) }}</div>
          </div>
          <div style="display: flex; gap: 0.4rem; flex-shrink: 0">
            <button
              class="btn btn-ghost text-sm"
              style="padding: 0.2rem 0.5rem"
              :disabled="syncingId === cert.id"
              @click="syncOne(cert)"
              title="Sync this cert to all online kiosks"
            >
              Sync
            </button>
            <button
              class="btn btn-ghost text-sm"
              style="padding: 0.2rem 0.5rem; color: var(--danger)"
              @click="deleteCert(cert)"
            >
              Delete
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { useToastStore } from '../stores/toast'
import { useApi } from '../composables/useApi'
import { useFeatureFlagsStore } from '../stores/featureFlags'

const flagStore = useFeatureFlagsStore()
const router = useRouter()
if (!flagStore.isEnabled('import_certs')) {
  router.replace('/settings')
}

const toast = useToastStore()
const { apiFetch } = useApi()

const loading = ref(true)
const adding = ref(false)
const syncing = ref(false)
const syncingId = ref(null)
const certs = ref([])
const pemError = ref('')

const form = ref({ name: '', description: '', content: '' })

function formatDate(ts) {
  return new Date(ts).toLocaleString()
}

function validatePem() {
  const v = form.value.content.trim()
  if (!v) {
    pemError.value = ''
    return true
  }
  if (!v.includes('-----BEGIN CERTIFICATE-----')) {
    pemError.value = 'Content must contain a PEM certificate (-----BEGIN CERTIFICATE-----)'
    return false
  }
  pemError.value = ''
  return true
}

function loadFile(event) {
  const file = event.target.files[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = e => {
    form.value.content = e.target.result
    validatePem()
  }
  reader.readAsText(file)
  event.target.value = ''
}

async function load() {
  try {
    certs.value = await apiFetch('/settings/certificates')
  } catch {
    // silent — empty state shown on load failure
  } finally {
    loading.value = false
  }
}

async function addCert() {
  if (!validatePem()) return
  adding.value = true
  try {
    const created = await apiFetch('/settings/certificates', {
      method: 'POST',
      body: JSON.stringify({
        name: form.value.name,
        description: form.value.description || null,
        content: form.value.content.trim(),
      }),
    })
    certs.value = [...certs.value, created].sort((a, b) => a.name.localeCompare(b.name))
    form.value = { name: '', description: '', content: '' }
    pemError.value = ''
    toast.add('Certificate added', 'success')
  } catch {
    toast.add('Failed to add certificate', 'error')
  } finally {
    adding.value = false
  }
}

async function deleteCert(cert) {
  if (!confirm(`Delete "${cert.name}"? It will be removed from all kiosks on the next sync.`)) return
  try {
    await apiFetch(`/settings/certificates/${cert.id}`, { method: 'DELETE' })
    certs.value = certs.value.filter(c => c.id !== cert.id)
    toast.add('Certificate deleted', 'success')
  } catch {
    toast.add('Failed to delete certificate', 'error')
  }
}

async function syncAll() {
  syncing.value = true
  try {
    await apiFetch('/settings/certificates/sync', { method: 'POST' })
    toast.add('Sync command sent to all online kiosks', 'success')
  } catch {
    toast.add('Failed to send sync command', 'error')
  } finally {
    syncing.value = false
  }
}

async function syncOne(cert) {
  syncingId.value = cert.id
  try {
    await apiFetch('/settings/certificates/sync', { method: 'POST' })
    toast.add(`Sync sent to all online kiosks`, 'success')
  } catch {
    toast.add('Failed to send sync command', 'error')
  } finally {
    syncingId.value = null
  }
}

load()
</script>
