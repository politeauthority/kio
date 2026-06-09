<template>
  <div>
    <div class="page-header">
      <div>
        <RouterLink to="/settings" class="text-muted text-sm" style="display: inline-flex; align-items: center; gap: 4px; margin-bottom: 0.4rem">
          ← Settings
        </RouterLink>
        <h1 class="page-title">Browser Flags</h1>
      </div>
      <button class="btn btn-primary" style="min-width: 64px" :disabled="saving || loading" @click="save">
        {{ saving ? 'Saving…' : 'Save' }}
      </button>
    </div>

    <div class="card" style="max-width: 560px">
      <p class="text-xs text-muted" style="margin-bottom: 1.25rem">
        Default Chromium flags applied to all nodes. Individual nodes can add their own flags on the edit page.
        Changes take effect after the next node reboot.
      </p>
      <div v-if="loading" class="text-muted text-sm">Loading…</div>
      <div v-else>
        <div style="display: flex; flex-direction: column; gap: 0.75rem; margin-bottom: var(--space-md)">
          <label
            v-for="f in KNOWN_FLAGS"
            :key="f.flag"
            style="display: flex; align-items: center; gap: 0.65rem; cursor: pointer"
          >
            <input
              type="checkbox"
              :checked="flagsSet.has(f.flag)"
              @change="toggleFlag(f.flag)"
              style="width: 15px; height: 15px; accent-color: var(--accent); cursor: pointer"
            />
            <span class="text-sm">{{ f.label }}</span>
            <code style="font-size: 0.75rem; color: var(--text-muted)">{{ f.flag }}</code>
          </label>
        </div>

        <div>
          <label class="form-label">Additional flags <span class="text-muted">(one per line)</span></label>
          <textarea
            v-model="customFlagsText"
            class="form-input"
            rows="3"
            placeholder="--disable-gpu"
            style="resize: vertical; font-family: monospace; font-size: 0.85rem"
          />
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
const flagsSet = ref(new Set())
const customFlagsText = ref('')

const KNOWN_FLAGS = [
  { flag: '--force-dark-mode',                label: 'Force dark mode' },
  { flag: '--hide-scrollbars',                label: 'Hide scrollbars' },
  { flag: '--ignore-certificate-errors',      label: 'Ignore certificate errors' },
  { flag: '--disable-session-crashed-bubble', label: 'Disable crash restore bubble' },
  { flag: '--no-first-run',                   label: 'Skip first-run setup' },
]

function initFlags(flags) {
  const known = new Set(KNOWN_FLAGS.map(f => f.flag))
  flagsSet.value = new Set(flags.filter(f => known.has(f)))
  customFlagsText.value = flags.filter(f => !known.has(f)).join('\n')
}

function toggleFlag(flag) {
  const s = new Set(flagsSet.value)
  s.has(flag) ? s.delete(flag) : s.add(flag)
  flagsSet.value = s
}

async function load() {
  try {
    const data = await apiFetch('/settings/node/browser-flags')
    initFlags(data.flags || [])
  } catch {
    toast.add('Failed to load browser flags', 'error')
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const custom = customFlagsText.value.split('\n').map(f => f.trim()).filter(f => f.startsWith('--'))
    const flags = [...flagsSet.value, ...custom]
    await apiFetch('/settings/node/browser-flags', {
      method: 'PUT',
      body: JSON.stringify({ flags }),
    })
    toast.add('Browser flags saved', 'success')
  } catch {
    toast.add('Failed to save browser flags', 'error')
  } finally {
    saving.value = false
  }
}

load()
</script>
