<template>
  <div>
    <div class="page-header">
      <div>
        <RouterLink to="/settings" class="text-muted text-sm" style="display: inline-flex; align-items: center; gap: 4px; margin-bottom: 0.4rem">
          ← Settings
        </RouterLink>
        <h1 class="page-title">Hosts</h1>
      </div>
      <button class="btn btn-primary" style="min-width: 64px" :disabled="saving || loading" @click="save">
        {{ saving ? 'Saving…' : 'Save' }}
      </button>
    </div>

    <div class="card" style="max-width: 600px">
      <p class="text-xs text-muted" style="margin-bottom: 1rem">
        Global <code>/etc/hosts</code> entries injected into every node at startup.
        Format: <code>IP hostname [hostname...]</code> — one entry per line.
        Per-node overrides can be set on the node's edit page.
      </p>
      <div v-if="loading" class="text-muted text-sm">Loading…</div>
      <div v-else>
        <textarea
          v-model="hostsText"
          class="form-input"
          :class="errors.length ? 'form-input-error' : ''"
          rows="8"
          placeholder="192.168.1.10 kio.example.local api.kio.example.local"
          style="resize: vertical; font-family: monospace; font-size: 0.85rem; line-height: 1.8"
          @input="validate"
        />
        <div v-if="errors.length" style="margin-top: 0.5rem">
          <div v-for="err in errors" :key="err" style="color: var(--danger); font-size: 0.8rem">{{ err }}</div>
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
const saving = ref(false)
const hostsText = ref('')
const errors = ref([])

const ipRe = /^\d{1,3}(\.\d{1,3}){3}$/

function validate() {
  const errs = []
  hostsText.value.split('\n').forEach((raw, i) => {
    const line = raw.trim()
    if (!line) return
    const parts = line.split(/\s+/)
    if (parts.length < 2) {
      errs.push(`Line ${i + 1}: must have at least one hostname after the IP`)
    } else if (!ipRe.test(parts[0])) {
      errs.push(`Line ${i + 1}: "${parts[0]}" is not a valid IPv4 address`)
    }
  })
  errors.value = errs
  return errs.length === 0
}

async function load() {
  try {
    const data = await apiFetch('/settings/node/hosts')
    hostsText.value = (data.hosts || []).join('\n')
  } catch {
    toast.add('Failed to load hosts settings', 'error')
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!validate()) {
    toast.add('Fix errors before saving', 'error')
    return
  }
  saving.value = true
  try {
    const hosts = hostsText.value.split('\n').map(l => l.trim()).filter(Boolean)
    await apiFetch('/settings/node/hosts', {
      method: 'PUT',
      body: JSON.stringify({ hosts }),
    })
    toast.add('Hosts saved', 'success')
  } catch {
    toast.add('Failed to save hosts', 'error')
  } finally {
    saving.value = false
  }
}

load()
</script>
