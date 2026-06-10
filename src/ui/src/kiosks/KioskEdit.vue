<template>
  <div v-if="kiosk">
    <div class="page-header">
      <div>
        <RouterLink :to="`/kiosks/${kioskId}`" class="text-muted text-sm" style="display: inline-flex; align-items: center; gap: 4px; margin-bottom: 0.4rem">
          ← {{ kiosk.name }}
        </RouterLink>
        <h1 class="page-title">Edit Kiosk</h1>
      </div>
      <button class="btn btn-primary" :disabled="saving" @click="save">
        {{ saving ? 'Saving…' : 'Save' }}
      </button>
    </div>

    <div class="edit-grid">

    <!-- Basic info -->
    <div class="card">
      <div class="card-header">Details</div>
      <div style="display: flex; flex-direction: column; gap: var(--space-md); max-width: 480px">
        <div>
          <label class="form-label">Name</label>
          <input v-model="form.name" class="form-input" required />
        </div>
        <div>
          <label class="form-label">Hostname</label>
          <input v-model="form.hostname" class="form-input" required />
        </div>
      </div>
    </div>

    <!-- Capabilities -->
    <div class="card mt-lg">
      <div class="card-header" style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0">
        <span>Capabilities</span>
        <button
          class="btn btn-secondary"
          style="padding: 0.25rem 0.75rem; font-size: 0.8rem"
          :disabled="detecting || blocked"
          @click="detectCapabilities"
        >
          {{ detecting ? 'Detecting…' : 'Detect Hardware' }}
        </button>
      </div>
      <p class="text-xs text-muted" style="margin-top: 0.5rem; margin-bottom: 0.75rem">
        Run detection when the display changes or when onboarding a new node. Results come back within ~15s.
      </p>
      <div style="display: flex; flex-direction: column; gap: 0.85rem">
        <div v-for="cap in KNOWN_CAPS" :key="cap.key">
          <label
            :style="{ display: 'flex', alignItems: 'center', gap: '0.65rem', cursor: capUnsupported(cap.key) ? 'not-allowed' : 'pointer', opacity: capUnsupported(cap.key) ? 0.55 : 1 }"
          >
            <input
              type="checkbox"
              :checked="featuresSet.has(cap.key)"
              :disabled="capUnsupported(cap.key)"
              @change="toggleFeature(cap.key)"
              style="width: 15px; height: 15px; accent-color: var(--accent)"
            />
            <span class="text-sm">{{ cap.label }}</span>
            <span class="text-xs text-muted">{{ cap.description }}</span>
          </label>
          <p
            v-if="capUnsupported(cap.key)"
            class="text-xs"
            style="margin: 0.3rem 0 0 1.75rem; color: var(--warning)"
          >
            ⚠ Disabled — {{ capUnsupportedReason(cap.key) }}. Re-run “Detect Hardware” after changing the display.
          </p>
          <label
            v-else-if="featuresSet.has(cap.key)"
            style="display: flex; align-items: center; gap: 0.65rem; cursor: pointer; margin-top: 0.35rem; margin-left: 1.75rem"
          >
            <input
              type="checkbox"
              :checked="!hiddenControls.has(cap.key)"
              @change="toggleControl(cap.key)"
              style="width: 13px; height: 13px; accent-color: var(--accent); cursor: pointer"
            />
            <span class="text-xs text-muted">Show on detail page</span>
          </label>
        </div>
      </div>
    </div>

    <!-- Display resolution -->
    <div v-if="Object.keys(displayModesFromLog(detectLog)).length" class="card mt-lg">
      <div class="card-header">Display Resolution</div>
      <p class="text-xs text-muted" style="margin-bottom: 0.75rem">
        Select a resolution and click Apply — it takes effect immediately and is saved so the node re-applies it after a reboot.
      </p>
      <div style="display: flex; flex-direction: column; gap: 0.6rem">
        <div
          v-for="(modes, output) in displayModesFromLog(detectLog)"
          :key="output"
          style="display: flex; align-items: center; gap: 0.75rem"
        >
          <span class="text-sm" style="min-width: 100px">{{ outputDisplayLabel(output) }}</span>
          <select
            v-model="selectedResolutions[output]"
            class="form-input"
            style="width: 240px"
          >
            <option v-for="m in modes" :key="`${m.mode}@${m.rate ?? 'x'}`" :value="`${m.mode}@${m.rate ?? ''}`">
              {{ m.mode }}{{ m.rate ? ` @ ${m.rate} Hz` : '' }}{{ m.current ? ' (current)' : '' }}{{ m.preferred ? ' ✓' : '' }}
            </option>
          </select>
          <button
            class="btn btn-secondary"
            style="padding: 0.25rem 0.75rem; font-size: 0.8rem"
            :disabled="settingResolution || blocked"
            @click="applyResolution(output)"
          >
            {{ settingResolution ? 'Applying…' : 'Apply' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Input configuration -->
    <div v-if="featuresSet.has('input_switch') && !capUnsupported('input_switch')" class="card mt-lg">
      <div class="card-header">Input Configuration</div>
      <p class="text-xs text-muted" style="margin-bottom: 0.75rem">
        Choose which inputs appear on the kiosk detail page and give them meaningful names.
      </p>
      <div style="display: flex; flex-direction: column; gap: 0.5rem">
        <div
          v-for="inp in ALL_INPUTS"
          :key="inp.value"
          style="display: flex; align-items: center; gap: 0.75rem"
        >
          <input
            type="checkbox"
            :checked="!hiddenInputs.has(inp.value)"
            style="width: 15px; height: 15px; accent-color: var(--accent); cursor: pointer; flex-shrink: 0"
            @change="toggleInput(inp.value)"
          />
          <input
            v-model="inputLabels[inp.value]"
            class="form-input"
            :placeholder="inp.defaultLabel"
            style="width: 200px"
          />
          <span class="text-xs text-muted">{{ inp.value }}</span>
        </div>
      </div>
    </div>

    <!-- Browser flags — temporarily hidden -->
    <!-- <div class="card mt-lg">
      <div class="card-header">Browser Flags</div>

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

      <p class="text-xs text-muted mt-md" style="color: var(--warning)">
        ⚠ Changes take effect after the next reboot
      </p>
    </div> -->

    <!-- Hosts — temporarily hidden -->
    <!-- <div class="card mt-lg">
      <div class="card-header">Hosts</div>
      <p class="text-xs text-muted" style="margin-bottom: 0.75rem">
        Injected into <code>/etc/hosts</code> on the node at startup. Format: <code>IP hostname [hostname...]</code> — one entry per line.
        Changes are applied on the next agent restart.
      </p>
      <textarea
        v-model="hostsText"
        class="form-input"
        :class="hostsErrors.length ? 'form-input-error' : ''"
        rows="5"
        placeholder="192.168.1.10 kio.example.local api.kio.example.local"
        style="resize: vertical; font-family: monospace; font-size: 0.85rem; line-height: 1.8"
        @input="validateHosts"
      />
      <div v-if="hostsErrors.length" style="margin-top: 0.5rem">
        <div v-for="err in hostsErrors" :key="err" style="color: var(--danger); font-size: 0.8rem">
          {{ err }}
        </div>
      </div>
    </div> -->

    <!-- Agent overrides -->
    <div class="card mt-lg">
      <div class="card-header">Agent Overrides</div>
      <p class="text-xs text-muted" style="margin-bottom: 0.75rem">
        Override the global agent defaults for this node only. Leave blank to use the default (shown as placeholder).
        Saving applies the change to the node immediately (or on its next checkin if offline).
      </p>
      <div style="display: flex; flex-direction: column; gap: var(--space-md); max-width: 360px">
        <div v-for="f in overrideFields" :key="f.key">
          <label class="form-label" style="display: flex; align-items: center; gap: 0.4rem">
            {{ f.label }} <span class="text-muted">(sec)</span>
            <span
              v-if="isOverridden(f.key)"
              style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--accent); flex-shrink: 0"
              :title="`Custom: ${overrides[f.key]} (default: ${agentDefaults[f.key]})`"
            />
          </label>
          <input
            v-model="overrides[f.key]"
            type="number"
            class="form-input"
            :class="isOverridden(f.key) ? 'form-input-overridden' : ''"
            :min="f.min"
            :max="f.max"
            :placeholder="agentDefaults[f.key] != null ? `default: ${agentDefaults[f.key]}` : 'default'"
          />
        </div>
      </div>
    </div>

    <!-- Node tokens -->
    <div class="card mt-lg">
      <div class="card-header" style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0">
        <span>Node Tokens</span>
        <button class="btn btn-secondary" style="padding: 0.25rem 0.75rem; font-size: 0.8rem" @click="showCreateTokenModal = true">
          + New Token
        </button>
      </div>

      <div v-if="tokens.length === 0" class="text-muted text-sm" style="margin-top: 1rem">
        No tokens yet.
      </div>

      <table v-else class="table" style="margin-top: 0.75rem">
        <thead>
          <tr>
            <th>Description</th>
            <th>Created</th>
            <th>Last Used</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="token in tokens" :key="token.id">
            <td class="text-sm">
              <span v-if="token.description">{{ token.description }}</span>
              <span v-else class="text-muted">—</span>
            </td>
            <td class="text-sm text-muted">{{ formatDate(token.created_at) }}</td>
            <td class="text-sm text-muted">{{ token.last_used_at ? formatDate(token.last_used_at) : 'never' }}</td>
            <td>
              <button class="btn btn-ghost text-sm" style="color: var(--danger); padding: 0.2rem 0.5rem" @click="revokeToken(token)">
                Revoke
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Danger zone -->
    <div class="card mt-lg" style="border-color: color-mix(in srgb, var(--danger) 30%, var(--border))">
      <div class="card-header" style="color: var(--danger)">Danger Zone</div>
      <div style="display: flex; align-items: center; justify-content: space-between">
        <div>
          <div class="text-sm" style="font-weight: 500">Delete this kiosk</div>
          <div class="text-xs text-muted mt-sm">Removes the kiosk and all associated tokens. This cannot be undone.</div>
        </div>
        <button class="btn btn-danger" @click="deleteKiosk">Delete Kiosk</button>
      </div>
    </div>

    </div><!-- /edit-grid -->

    <!-- Create Token Modal -->
    <div v-if="showCreateTokenModal" class="dialog-backdrop" @click.self="showCreateTokenModal = false">
      <div class="dialog">
        <h2 class="dialog-title">New Node Token</h2>
        <form @submit.prevent="createToken">
          <div class="mt-md">
            <label class="form-label">Description <span class="text-muted">(optional)</span></label>
            <input v-model="tokenForm.description" class="form-input" placeholder="e.g. lobby display" autofocus />
          </div>
          <div class="dialog-actions">
            <button type="button" class="btn btn-secondary" @click="showCreateTokenModal = false">Cancel</button>
            <button type="submit" class="btn btn-primary" :disabled="creatingToken">
              {{ creatingToken ? 'Creating…' : 'Create Token' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- New Token Display Modal -->
    <div v-if="newToken" class="dialog-backdrop">
      <div class="dialog">
        <h2 class="dialog-title">Token Created</h2>
        <p class="text-sm text-muted" style="margin-bottom: 1rem">Copy this token now — it won't be shown again.</p>
        <div style="background: var(--bg-dark); border: 1px solid var(--border); border-radius: var(--radius); padding: 0.75rem 1rem; font-family: monospace; font-size: 0.82rem; word-break: break-all; color: var(--text-primary); user-select: all">
          {{ newToken }}
        </div>
        <div class="dialog-actions">
          <button class="btn btn-secondary" @click="copyToken">Copy</button>
          <button class="btn btn-primary" @click="newToken = null">Done</button>
        </div>
      </div>
    </div>
  </div>

  <div v-else-if="loading" class="text-muted text-sm">Loading…</div>
  <div v-else class="empty-state">Kiosk not found.</div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { useApi } from '../composables/useApi'
import { usePendingCommand } from '../composables/usePendingCommand'
import { useToastStore } from '../stores/toast'

const route = useRoute()
const router = useRouter()
const { apiFetch } = useApi()
const toast = useToastStore()

const kioskId = computed(() => route.params.id)
const { pendingCommand, blocked, refresh: refreshPending } = usePendingCommand(kioskId)

watch(() => pendingCommand.value?.id, (id) => {
  if (id && blocked.value) {
    toast.add(`Commands paused — waiting for "${pendingCommand.value.command}" to finish`, 'warning')
  }
})

const kiosk = ref(null)
const loading = ref(true)
const saving = ref(false)
const form = ref({ name: '', hostname: '' })
const hostsText = ref('')
const hostsErrors = ref([])

function validateHosts() {
  const ipRe = /^\d{1,3}(\.\d{1,3}){3}$/
  const errors = []
  hostsText.value.split('\n').forEach((raw, i) => {
    const line = raw.trim()
    if (!line) return
    const parts = line.split(/\s+/)
    if (parts.length < 2) {
      errors.push(`Line ${i + 1}: must have at least one hostname after the IP — "${line}"`)
    } else if (!ipRe.test(parts[0])) {
      errors.push(`Line ${i + 1}: "${parts[0]}" is not a valid IPv4 address`)
    }
  })
  hostsErrors.value = errors
  return errors.length === 0
}
const flagsSet = ref(new Set())
const customFlagsText = ref('')
const tokens = ref([])
const showCreateTokenModal = ref(false)
const creatingToken = ref(false)
const tokenForm = ref({ description: '' })
const newToken = ref(null)

const KNOWN_CAPS = [
  { key: 'display_power', label: 'Display power',  description: 'Control display on/off via DDC/CI (VCP D6)' },
  { key: 'cec',           label: 'HDMI CEC',        description: 'Send CEC commands (standby, wake) via /dev/cec0' },
  { key: 'input_switch',  label: 'Input switching', description: 'Switch display inputs via DDC/CI (VCP 60)' },
]

// Latest hardware-detection result. When a probe explicitly reported the display
// does NOT support a capability, we disable that capability's toggle so it can't
// be enabled, and explain why.
const detectLog = ref(null)

function capUnsupported(key) {
  const probe = detectLog.value?.probes?.[key]
  return !!probe && probe.detected === false
}

function capUnsupportedReason(key) {
  const probe = detectLog.value?.probes?.[key]
  if (!probe) return ''
  const detail = probe.error || probe.stderr || (probe.returncode !== undefined ? `exit ${probe.returncode}` : '')
  return detail ? `the connected display does not support it (${detail})` : 'the connected display does not support it'
}

const ALL_INPUTS = [
  { value: 'dp1',   defaultLabel: 'DP 1' },
  { value: 'dp2',   defaultLabel: 'DP 2' },
  { value: 'hdmi1', defaultLabel: 'HDMI 1' },
  { value: 'hdmi2', defaultLabel: 'HDMI 2' },
]

const inputLabels = ref({})   // { dp1: 'Custom Name', ... }
const hiddenInputs = ref(new Set())
const hiddenControls = ref(new Set())

function toggleInput(key) {
  const s = new Set(hiddenInputs.value)
  s.has(key) ? s.delete(key) : s.add(key)
  hiddenInputs.value = s
}

function toggleControl(key) {
  const s = new Set(hiddenControls.value)
  s.has(key) ? s.delete(key) : s.add(key)
  hiddenControls.value = s
}

const featuresSet = ref(new Set())
const detecting = ref(false)

// Resolution: map of output name -> selected mode string "WxH@R" or "WxH"
const selectedResolutions = ref({})
const settingResolution = ref(false)

function displayModesFromLog(log) {
  const modes = log?.hardware_info?.display_modes ?? {}
  // Limit resolution control to the kiosk's active display (the output at
  // position 0,0). Falls back to all outputs for older detect logs.
  const primary = log?.hardware_info?.primary_output
  if (primary && primary in modes) return { [primary]: modes[primary] }
  return modes
}

// Map wlr-randr output names to the input keys used by inputLabels
const OUTPUT_TO_INPUT_KEY = {
  'HDMI-A-1': 'hdmi1',
  'HDMI-A-2': 'hdmi2',
  'DP-1':     'dp1',
  'DP-2':     'dp2',
}

function outputDisplayLabel(output) {
  const normalized = output.replace(/^card\d+-/, '')
  const key = OUTPUT_TO_INPUT_KEY[normalized]
  if (key && inputLabels.value[key]) return inputLabels.value[key]
  const inp = ALL_INPUTS.find(i => i.value === key)
  if (inp) return inp.defaultLabel
  return output
}

function initResolutionSelections(log) {
  const dm = displayModesFromLog(log)
  const next = {}
  for (const [output, modes] of Object.entries(dm)) {
    const current = modes.find(m => m.current)
    const seed = current ?? modes[0]
    next[output] = seed ? `${seed.mode}@${seed.rate ?? ''}` : ''
  }
  selectedResolutions.value = next
}

async function applyResolution(output) {
  const val = selectedResolutions.value[output]
  if (!val) return
  const atIdx = val.lastIndexOf('@')
  const mode = atIdx !== -1 ? val.slice(0, atIdx) : val
  const rateStr = atIdx !== -1 ? val.slice(atIdx + 1) : ''
  const rate = rateStr ? parseFloat(rateStr) : null
  settingResolution.value = true
  try {
    await apiFetch(`/kiosks/${kioskId.value}/set-resolution`, {
      method: 'POST',
      body: JSON.stringify({ output, mode, rate }),
    })
    toast.add(`Resolution change sent: ${output} ${mode}${rate ? ` @ ${rate} Hz` : ''}`, 'success')
  } catch {
    toast.add('Failed to set resolution', 'error')
  } finally {
    settingResolution.value = false
  }
}

function isOverridden(key) {
  const val = overrides.value[key]
  if (val === '' || val == null || Number.isNaN(Number(val))) return false
  return Number(val) !== agentDefaults.value[key]
}

// Per-node agent setting overrides. Only a subset of global settings may be
// overridden per node; blank fields fall back to the global default.
const overrideFields = [
  { key: 'heartbeat_interval_seconds', label: 'Heartbeat interval', min: 5, max: 3600 },
  { key: 'heartbeat_jitter_seconds', label: 'Heartbeat jitter', min: 0, max: 300 },
  { key: 'metadata_interval_seconds', label: 'Metadata heartbeat interval', min: 60, max: 86400 },
]
const agentDefaults = ref({})
const overrides = ref({})

function toggleFeature(key) {
  const s = new Set(featuresSet.value)
  if (s.has(key)) {
    s.delete(key)
  } else {
    if (capUnsupported(key)) return  // can't enable a capability the display doesn't support
    s.add(key)
  }
  featuresSet.value = s
}

async function detectCapabilities() {
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
    // Poll for updated features — the agent reports back via heartbeat
    const before = [...featuresSet.value].sort().join()
    let attempts = 0
    const poll = setInterval(async () => {
      attempts++
      try {
        const k = await apiFetch(`/kiosks/${kioskId.value}`)
        const after = [...(k.features || [])].sort().join()
        if (after !== before || attempts >= 15) {
          clearInterval(poll)
          detecting.value = false
          featuresSet.value = new Set(k.features || [])
          if (after !== before) toast.add(`Detected: ${k.features.join(', ') || 'none'}`, 'success')
          else toast.add('Detection complete — no changes', 'info')
          // Refresh detect log so display_modes update immediately
          const log = await apiFetch(`/kiosks/${kioskId.value}/hardware-detect-log`).catch(() => null)
          detectLog.value = log
          initResolutionSelections(log)
        }
      } catch { clearInterval(poll); detecting.value = false }
    }, 2000)
  } catch {
    toast.add('Failed to start detection', 'error')
    detecting.value = false
  }
}

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
    const [k, t, log, defaults] = await Promise.all([
      apiFetch(`/kiosks/${kioskId.value}`),
      apiFetch(`/kiosks/${kioskId.value}/tokens`),
      apiFetch(`/kiosks/${kioskId.value}/hardware-detect-log`).catch(() => null),
      apiFetch('/settings/agent').catch(() => ({})),
    ])
    kiosk.value = k
    form.value = { name: k.name, hostname: k.hostname }
    featuresSet.value = new Set(k.features || [])
    initFlags(k.browser_flags || [])
    hostsText.value = (k.meta?.extra_hosts || []).join('\n\n')
    inputLabels.value = { ...(k.meta?.input_labels ?? {}) }
    hiddenInputs.value = new Set(k.meta?.hidden_inputs ?? [])
    hiddenControls.value = new Set(k.meta?.hidden_controls ?? [])
    agentDefaults.value = defaults || {}
    overrides.value = { ...(k.meta?.settings_overrides ?? {}) }
    tokens.value = t
    detectLog.value = log
    initResolutionSelections(log)
  } catch {
    toast.add('Failed to load kiosk', 'error')
  } finally {
    loading.value = false
  }
}

async function createToken() {
  creatingToken.value = true
  try {
    const created = await apiFetch(`/kiosks/${kioskId.value}/tokens`, {
      method: 'POST',
      body: JSON.stringify({ description: tokenForm.value.description || null }),
    })
    newToken.value = created.token
    showCreateTokenModal.value = false
    tokenForm.value = { description: '' }
    tokens.value = await apiFetch(`/kiosks/${kioskId.value}/tokens`)
  } catch {
    toast.add('Failed to create token', 'error')
  } finally {
    creatingToken.value = false
  }
}

async function revokeToken(token) {
  if (!confirm('Revoke this token? The node using it will stop working.')) return
  try {
    await apiFetch(`/kiosks/${kioskId.value}/tokens/${token.id}`, { method: 'DELETE' })
    tokens.value = tokens.value.filter(t => t.id !== token.id)
    toast.add('Token revoked', 'success')
  } catch {
    toast.add('Failed to revoke token', 'error')
  }
}

async function copyToken() {
  try {
    await navigator.clipboard.writeText(newToken.value)
    toast.add('Token copied', 'success')
  } catch {
    toast.add('Copy failed — select and copy manually', 'error')
  }
}

function formatDate(ts) {
  return new Date(ts).toLocaleString()
}

async function save() {
  saving.value = true
  try {
    const custom = customFlagsText.value.split('\n').map(f => f.trim()).filter(f => f.startsWith('--'))
    const flags = [...flagsSet.value, ...custom]

    if (!validateHosts()) {
      toast.add('Fix hosts errors before saving', 'error')
      return
    }
    const hosts = hostsText.value.split('\n').map(l => l.trim()).filter(Boolean)

    // Strip empty-string labels (treat as "use default")
    const cleanedLabels = Object.fromEntries(
      Object.entries(inputLabels.value).filter(([, v]) => v && v.trim())
    )

    // Only persist overrides that have a real value; blanks mean "use default".
    const cleanedOverrides = {}
    for (const f of overrideFields) {
      const v = overrides.value[f.key]
      if (v !== '' && v != null && !Number.isNaN(Number(v))) cleanedOverrides[f.key] = Number(v)
    }

    await Promise.all([
      apiFetch(`/kiosks/${kioskId.value}`, {
        method: 'PATCH',
        body: JSON.stringify({ ...form.value, features: [...featuresSet.value] }),
      }),
      apiFetch(`/kiosks/${kioskId.value}/browser-flags`, {
        method: 'PUT',
        body: JSON.stringify({ flags }),
      }),
      apiFetch(`/kiosks/${kioskId.value}/meta/extra_hosts`, {
        method: 'PUT',
        body: JSON.stringify({ key: 'extra_hosts', value: hosts }),
      }),
      apiFetch(`/kiosks/${kioskId.value}/meta/input_labels`, {
        method: 'PUT',
        body: JSON.stringify({ key: 'input_labels', value: cleanedLabels }),
      }),
      apiFetch(`/kiosks/${kioskId.value}/meta/hidden_inputs`, {
        method: 'PUT',
        body: JSON.stringify({ key: 'hidden_inputs', value: [...hiddenInputs.value] }),
      }),
      apiFetch(`/kiosks/${kioskId.value}/meta/hidden_controls`, {
        method: 'PUT',
        body: JSON.stringify({ key: 'hidden_controls', value: [...hiddenControls.value] }),
      }),
      apiFetch(`/kiosks/${kioskId.value}/meta/settings_overrides`, {
        method: 'PUT',
        body: JSON.stringify({ key: 'settings_overrides', value: cleanedOverrides }),
      }),
    ])
    toast.add('Kiosk saved', 'success')
    router.push(`/kiosks/${kioskId.value}`)
  } catch {
    toast.add('Failed to save kiosk', 'error')
  } finally {
    saving.value = false
  }
}

async function deleteKiosk() {
  if (!confirm(`Delete ${kiosk.value.name}? This cannot be undone.`)) return
  try {
    await apiFetch(`/kiosks/${kioskId.value}`, { method: 'DELETE' })
    toast.add(`${kiosk.value.name} deleted`, 'success')
    router.push('/')
  } catch {
    toast.add('Failed to delete kiosk', 'error')
  }
}

load()
</script>
