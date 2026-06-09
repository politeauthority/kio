<template>
  <div>
    <div class="page-header">
      <div>
        <RouterLink to="/settings" class="text-muted text-sm" style="display: inline-flex; align-items: center; gap: 4px; margin-bottom: 0.4rem">
          ← Settings
        </RouterLink>
        <h1 class="page-title">Feature Flags</h1>
      </div>
    </div>

    <div class="card" style="max-width: 560px">
      <div style="display: flex; flex-direction: column; gap: 0">
        <div
          v-for="(flag, idx) in flagDefs"
          :key="flag.key"
          style="display: flex; align-items: center; justify-content: space-between; padding: 0.875rem 0"
          :style="idx < flagDefs.length - 1 ? 'border-bottom: 1px solid var(--border)' : ''"
        >
          <div>
            <div class="text-sm" style="font-weight: 500">{{ flag.label }}</div>
            <div class="text-xs text-muted" style="margin-top: 0.2rem">{{ flag.description }}</div>
          </div>
          <button
            class="btn"
            :class="flagStore.isEnabled(flag.key) ? 'btn-primary' : 'btn-secondary'"
            style="min-width: 64px"
            :disabled="saving === flag.key"
            @click="toggle(flag.key)"
          >
            {{ flagStore.isEnabled(flag.key) ? 'On' : 'Off' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { useFeatureFlagsStore } from '../stores/featureFlags'
import { useToastStore } from '../stores/toast'
import { SHOW_FEATURE_FLAGS } from '../config'

const router = useRouter()
onMounted(() => {
  if (!SHOW_FEATURE_FLAGS) router.replace('/settings')
})

const flagStore = useFeatureFlagsStore()
const toast = useToastStore()
const saving = ref(null)

const flagDefs = [
  {
    key: 'browser_management',
    label: 'Browser Management',
    description: 'Show the Browsers section on kiosk detail pages.',
  },
  {
    key: 'playlists',
    label: 'Playlists',
    description: 'Show the Playlists section on kiosk detail pages and the Playlists nav item.',
  },
  {
    key: 'debug',
    label: 'Debug',
    description: 'Show debug page links on kiosk detail pages.',
  },
  {
    key: 'import_certs',
    label: 'Import Certs',
    description: 'Show the Certificates settings page for syncing CA certs to kiosk nodes.',
  },
]

async function toggle(key) {
  saving.value = key
  try {
    await flagStore.set(key, !flagStore.isEnabled(key))
    toast.add(`${key} ${flagStore.isEnabled(key) ? 'enabled' : 'disabled'}`, 'success')
  } catch {
    toast.add('Failed to update feature flag', 'error')
  } finally {
    saving.value = null
  }
}
</script>
