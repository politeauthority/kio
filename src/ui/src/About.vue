<template>
  <div class="view-header">
    <h1>About</h1>
  </div>

  <div class="card p-4" style="max-width: 480px;">
    <table class="table table-sm mb-0">
      <tbody>
        <tr>
          <td class="text-secondary">Version</td>
          <td>
            <span v-if="version">{{ version }}</span>
            <span v-else class="text-secondary">—</span>
          </td>
        </tr>
        <tr>
          <td class="text-secondary">API</td>
          <td>
            <span v-if="apiUrl" class="font-monospace small">{{ apiUrl }}</span>
          </td>
        </tr>
        <tr>
          <td class="text-secondary">API status</td>
          <td>
            <span v-if="healthy === true" class="text-success">ok</span>
            <span v-else-if="healthy === false" class="text-danger">unreachable</span>
            <span v-else class="text-secondary">checking…</span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { API_URL } from './config'
import { useApi } from './composables/useApi'

const { apiFetch } = useApi()
const version = ref(null)
const healthy = ref(null)
const apiUrl = ref(API_URL)

onMounted(async () => {
  try {
    const data = await apiFetch('/_version')
    version.value = data.version
  } catch {
    version.value = 'unknown'
  }
  try {
    const data = await apiFetch('/_health')
    healthy.value = data.status === 'ok'
  } catch {
    healthy.value = false
  }
})
</script>
