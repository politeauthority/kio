<template>
  <div v-if="kiosk">
    <div class="page-header">
      <div>
        <RouterLink :to="`/kiosks/${kioskId}`" class="text-muted text-sm">← {{ kiosk.name }}</RouterLink>
        <h1 class="page-title mt-sm">Debug</h1>
        <p class="page-subtitle">{{ kiosk.hostname }} &middot; {{ kiosk.ip_address }}</p>
      </div>
      <button class="btn btn-secondary" @click="load">Refresh</button>
    </div>

    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem">

      <!-- Hardware -->
      <div class="card">
        <div class="card-header">Hardware</div>
        <table class="debug-table">
          <tr><td>Device</td><td>{{ kiosk.device_type || '—' }}</td></tr>
          <tr><td>IP Address</td><td><code>{{ kiosk.ip_address || '—' }}</code></td></tr>
          <tr><td>Agent Version</td><td><code>v{{ kiosk.agent_version || '—' }}</code></td></tr>
          <tr><td>Kiosk ID</td><td><code style="font-size: 0.72rem">{{ kiosk.id }}</code></td></tr>
          <tr><td>Hostname</td><td><code>{{ kiosk.hostname }}</code></td></tr>
          <tr><td>Registered</td><td>{{ fmt(kiosk.created_at) }}</td></tr>
        </table>
      </div>

      <!-- Live Status -->
      <div class="card">
        <div class="card-header">Live Status</div>
        <table class="debug-table">
          <tr>
            <td>Connection</td>
            <td><span class="status-badge" :class="`status-${kiosk.status}`">{{ kiosk.status }}</span></td>
          </tr>
          <tr><td>Last Seen</td><td>{{ fmt(kiosk.last_seen) }}</td></tr>
          <tr>
            <td>Display</td>
            <td>
              <span v-if="kiosk.display_on === true" style="color: var(--success)">On</span>
              <span v-else-if="kiosk.display_on === false" style="color: var(--danger)">Off</span>
              <span v-else class="text-muted">Unknown</span>
            </td>
          </tr>
          <tr>
            <td>Input</td>
            <td><code v-if="kiosk.current_input">{{ kiosk.current_input }}</code><span v-else class="text-muted">—</span></td>
          </tr>
          <tr>
            <td>Current URL</td>
            <td>
              <a v-if="kiosk.current_url" :href="kiosk.current_url" target="_blank" rel="noopener"
                 style="font-size: 0.78rem; word-break: break-all">
                {{ kiosk.current_url }}
              </a>
              <span v-else class="text-muted">—</span>
            </td>
          </tr>
        </table>
      </div>

    </div>

    <!-- Capabilities -->
    <div class="card mt-lg">
      <div class="card-header" style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0">
        <span>Capabilities</span>
        <button class="btn btn-secondary" style="padding: 0.25rem 0.75rem; font-size: 0.8rem"
          :disabled="detecting || blocked" @click="detect">
          {{ detecting ? 'Detecting…' : 'Detect Hardware' }}
        </button>
      </div>
      <p class="text-xs text-muted" style="margin-top: 0.4rem; margin-bottom: 1rem">
        Detection probes the hardware and updates within ~15s.
      </p>
      <table class="table">
        <thead>
          <tr>
            <th>Capability</th>
            <th>Status</th>
            <th>Method</th>
            <th>Description</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="cap in ALL_CAPS" :key="cap.key">
            <td class="text-sm" style="font-weight: 500">{{ cap.label }}</td>
            <td>
              <span v-if="kiosk.features.includes(cap.key)" style="color: var(--success); font-weight: 600">✓ detected</span>
              <span v-else class="text-muted text-xs">not detected</span>
            </td>
            <td><code style="font-size: 0.75rem">{{ cap.method }}</code></td>
            <td class="text-sm text-muted">{{ cap.description }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Last Detection Run -->
    <div class="card mt-lg">
      <div class="card-header" style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0">
        <span>Last Detection Run</span>
        <span v-if="detectLog" class="text-xs text-muted">{{ fmt(detectLog.detected_at) }}</span>
      </div>
      <div v-if="!detectLog" class="text-sm text-muted" style="margin-top: 1rem">
        No detection run yet — click <strong>Detect Hardware</strong> above to probe the hardware.
      </div>
      <template v-else>
        <table class="table" style="margin-top: 1rem">
          <thead>
            <tr>
              <th>Probe</th>
              <th>Result</th>
              <th>Command</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(probe, key) in detectLog.probes" :key="key">
              <td style="font-weight: 500; font-size: 0.875rem">{{ key }}</td>
              <td>
                <span v-if="probe.detected" style="color: var(--success); font-weight: 600">✓ detected</span>
                <span v-else style="color: var(--danger); font-weight: 600">✗ not detected</span>
              </td>
              <td><code style="font-size: 0.72rem">{{ probe.cmd }}</code></td>
              <td style="font-size: 0.78rem; color: var(--text-muted); max-width: 320px">
                <span v-if="probe.error" style="color: var(--danger)">{{ probe.error }}</span>
                <span v-else-if="probe.physical_address">
                  CEC addr: <code style="font-size: 0.72rem">{{ probe.physical_address }}</code>
                </span>
                <span v-else-if="probe.returncode !== undefined">
                  exit {{ probe.returncode }}<span v-if="probe.stderr"> — {{ probe.stderr.slice(0, 80) }}</span>
                </span>
              </td>
            </tr>
          </tbody>
        </table>
        <details v-if="detectLog.hardware_info?.cec" style="margin-top: 0.75rem">
          <summary class="text-xs text-muted" style="cursor: pointer; user-select: none">CEC bus details</summary>
          <table class="debug-table" style="margin-top: 0.5rem; max-width: 360px">
            <tr v-for="(v, k) in detectLog.hardware_info.cec" :key="k">
              <td>{{ k }}</td><td><code>{{ v }}</code></td>
            </tr>
          </table>
        </details>
      </template>
    </div>

    <!-- Hardware Report -->
    <div v-if="kiosk.meta?.hardware_info" class="card mt-lg">
      <div class="card-header">Hardware Report</div>
      <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1.5rem; align-items: start">

        <!-- System -->
        <div>
          <div class="text-xs text-muted" style="margin-bottom: 0.5rem; letter-spacing: 0.04em">SYSTEM</div>
          <table class="debug-table">
            <tr v-if="hw.os"><td>OS</td><td>{{ hw.os }}</td></tr>
            <tr v-if="hw.kernel"><td>Kernel</td><td><code>{{ hw.kernel }}</code></td></tr>
            <tr v-if="hw.board_model"><td>Board</td><td>{{ hw.board_model }}</td></tr>
            <tr v-if="hw.cpu_hardware"><td>CPU</td><td>{{ hw.cpu_hardware }}</td></tr>
            <tr v-if="hw.cpu_cores"><td>Cores</td><td>{{ hw.cpu_cores }}</td></tr>
            <tr v-if="hw.board_revision"><td>Revision</td><td><code>{{ hw.board_revision }}</code></td></tr>
          </table>
        </div>

        <!-- Memory & Storage -->
        <div>
          <div class="text-xs text-muted" style="margin-bottom: 0.5rem; letter-spacing: 0.04em">MEMORY & STORAGE</div>
          <table class="debug-table">
            <tr v-if="hw.ram_mb"><td>RAM</td><td>{{ hw.ram_mb }} MB</td></tr>
            <tr v-if="hw.gpu_mem_mb"><td>GPU Mem</td><td>{{ hw.gpu_mem_mb }} MB</td></tr>
            <tr v-if="hw.cpu_temp"><td>Temp</td><td>{{ hw.cpu_temp }}</td></tr>
            <tr v-if="hw.storage"><td>Disk Total</td><td>{{ hw.storage.total }}</td></tr>
            <tr v-if="hw.storage"><td>Disk Used</td><td>{{ hw.storage.used }} ({{ hw.storage.use_pct }})</td></tr>
            <tr v-if="hw.storage"><td>Disk Free</td><td>{{ hw.storage.free }}</td></tr>
          </table>
        </div>

        <!-- Display -->
        <div>
          <div class="text-xs text-muted" style="margin-bottom: 0.5rem; letter-spacing: 0.04em">DISPLAY</div>
          <div v-if="hw.display">
            <table class="debug-table">
              <tr v-if="hw.display.manufacturer"><td>Make</td><td>{{ hw.display.manufacturer }}</td></tr>
              <tr v-if="hw.display.model"><td>Model</td><td>{{ hw.display.model }}</td></tr>
              <tr v-if="hw.display.serial"><td>Serial</td><td><code>{{ hw.display.serial }}</code></td></tr>
              <tr v-if="hw.display.product_code"><td>Product</td><td><code>{{ hw.display.product_code }}</code></td></tr>
            </table>
          </div>
          <span v-else class="text-muted text-sm">No display detected via DDC/CI</span>
        </div>

      </div>
    </div>

    <!-- Browser Flags -->
    <div class="card mt-lg">
      <div class="card-header">Active Browser Flags</div>
      <div style="display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.25rem">
        <code
          v-for="flag in CORE_FLAGS"
          :key="flag"
          style="font-size: 0.75rem; padding: 0.2rem 0.5rem; background: var(--bg-surface-elevated); border: 1px solid var(--border); border-radius: var(--radius-sm); color: var(--text-muted)"
        >{{ flag }} <span style="color: var(--text-dim); font-size: 0.65rem">core</span></code>
        <code
          v-for="flag in kiosk.browser_flags"
          :key="flag"
          style="font-size: 0.75rem; padding: 0.2rem 0.5rem; background: var(--bg-surface-elevated); border: 1px solid var(--border); border-radius: var(--radius-sm)"
        >{{ flag }}</code>
      </div>
    </div>

    <!-- Raw JSON -->
    <div class="card mt-lg">
      <div class="card-header" style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0; cursor: pointer" @click="showRaw = !showRaw">
        <span>Raw Record</span>
        <span class="text-xs text-muted">{{ showRaw ? 'Hide' : 'Show' }}</span>
      </div>
      <pre v-if="showRaw" style="margin-top: 1rem; font-size: 0.75rem; overflow-x: auto; color: var(--text-secondary); white-space: pre-wrap; word-break: break-all">{{ JSON.stringify(kiosk, null, 2) }}</pre>
    </div>
  </div>

  <div v-else-if="loading" class="text-muted text-sm">Loading…</div>
  <div v-else class="empty-state">Kiosk not found.</div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { useApi } from '../composables/useApi'
import { usePendingCommand } from '../composables/usePendingCommand'
import { useToastStore } from '../stores/toast'

const route = useRoute()
const { apiFetch } = useApi()
const toast = useToastStore()

const kioskId = computed(() => route.params.id)
const { pendingCommand, blocked, refresh: refreshPending } = usePendingCommand(kioskId)

watch(() => pendingCommand.value?.id, (id) => {
  if (id) {
    toast.add(`Commands paused — waiting for "${pendingCommand.value.command}" to finish`, 'warning')
  }
})
const kiosk = ref(null)
const detectLog = ref(null)
const loading = ref(true)
const detecting = ref(false)
const showRaw = ref(false)

const hw = computed(() => kiosk.value?.meta?.hardware_info ?? {})

const ALL_CAPS = [
  {
    key: 'display_power',
    label: 'Display Power',
    method: 'ddcutil getvcp D6',
    description: 'Control display on/off via DDC/CI VCP feature D6 over HDMI I2C bus',
  },
  {
    key: 'cec',
    label: 'HDMI CEC',
    method: '/dev/cec0 + cec-ctl',
    description: 'Send CEC commands (standby, wake, active source) over the HDMI CEC bus',
  },
  {
    key: 'input_switch',
    label: 'Input Switching',
    method: 'ddcutil getvcp/setvcp 60',
    description: 'Read and switch display inputs (DP1, DP2, HDMI1, HDMI2) via DDC/CI VCP feature 60',
  },
]

const CORE_FLAGS = [
  '--password-store=basic',
  '--kiosk',
  '--remote-debugging-port=9222',
  '--remote-allow-origins=http://localhost:9222',
  '--hide-crash-restore-bubble',
]

async function load() {
  try {
    ;[kiosk.value, detectLog.value] = await Promise.all([
      apiFetch(`/kiosks/${kioskId.value}`),
      apiFetch(`/kiosks/${kioskId.value}/hardware-detect-log`).catch(() => null),
    ])
  } catch {
    toast.add('Failed to load kiosk', 'error')
  } finally {
    loading.value = false
  }
}

async function detect() {
  if (blocked.value) {
    toast.add(`Wait for "${pendingCommand.value.command}" to finish first`, 'info')
    return
  }
  detecting.value = true
  toast.add('Detection started — results in ~15s', 'info')
  try {
    await apiFetch(`/kiosks/${kioskId.value}/command`, {
      method: 'POST',
      body: JSON.stringify({ command: 'detect_capabilities' }),
    })
    await refreshPending()
    const sentAt = Date.now()
    let attempts = 0
    const poll = setInterval(async () => {
      attempts++
      try {
        const [k, log] = await Promise.all([
          apiFetch(`/kiosks/${kioskId.value}`),
          apiFetch(`/kiosks/${kioskId.value}/hardware-detect-log`).catch(() => null),
        ])
        const logIsNew = log && new Date(log.detected_at).getTime() > sentAt
        if (logIsNew || attempts >= 15) {
          clearInterval(poll)
          detecting.value = false
          kiosk.value = k
          detectLog.value = log
          if (logIsNew) toast.add(`Detected: ${k.features.join(', ') || 'none'}`, 'success')
          else toast.add('Detection timed out — no response from agent', 'warning')
        }
      } catch { clearInterval(poll); detecting.value = false }
    }, 2000)
  } catch {
    toast.add('Failed to start detection', 'error')
    detecting.value = false
  }
}

function fmt(ts) {
  if (!ts) return '—'
  return new Date(ts).toLocaleString()
}

load()
</script>

<style scoped>
.debug-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.875rem;
}
.debug-table td {
  padding: 0.4rem 0;
  vertical-align: top;
}
.debug-table td:first-child {
  color: var(--text-muted);
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  width: 110px;
  padding-right: 1rem;
  padding-top: 0.45rem;
}
.debug-table tr + tr td {
  border-top: 1px solid var(--border-subtle);
}
</style>
