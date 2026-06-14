<template>
  <div>
    <div class="page-header">
      <div>
        <RouterLink to="/settings" class="text-muted text-sm" style="display: inline-flex; align-items: center; gap: 4px; margin-bottom: 0.4rem">
          ← Settings
        </RouterLink>
        <h1 class="page-title">Display</h1>
      </div>
      <button class="btn btn-primary" style="min-width: 64px" :disabled="saving || loading" @click="save">
        {{ saving ? 'Saving…' : 'Save' }}
      </button>
    </div>

    <div class="card" style="max-width: 560px">
      <p class="text-xs text-muted" style="margin-bottom: 1.25rem">
        Display controls applied to nodes. Saving pushes changes to online nodes immediately;
        others pick them up on their next checkin. Individual nodes can override these on their edit page.
      </p>
      <div v-if="loading" class="text-muted text-sm">Loading…</div>
      <div v-else style="display: flex; flex-direction: column; gap: var(--space-md)">

        <!-- Brightness feature gate. Off by default (dark launch); flip on to expose
             the per-node brightness slider on capable (DDC/CI) displays. -->
        <div style="display: flex; align-items: center; justify-content: space-between; gap: 1rem">
          <div>
            <div class="text-sm" style="font-weight: 500">Brightness control</div>
            <div class="text-xs text-muted" style="margin-top: 0.2rem">
              Enable the brightness slider on capable (DDC/CI) displays. Off by default; can be overridden per node.
            </div>
          </div>
          <button
            class="btn"
            :class="settings.brightness_enabled ? 'btn-primary' : 'btn-secondary'"
            style="min-width: 64px; flex-shrink: 0"
            @click="settings.brightness_enabled = settings.brightness_enabled ? 0 : 1"
          >
            {{ settings.brightness_enabled ? 'On' : 'Off' }}
          </button>
        </div>

        <!-- Default luminance applied when the gate is enabled for a node. -->
        <div style="display: flex; align-items: center; justify-content: space-between; gap: 1rem">
          <div>
            <div class="text-sm" style="font-weight: 500">Default brightness</div>
            <div class="text-xs text-muted" style="margin-top: 0.2rem">
              Luminance applied when the brightness control is enabled for a node.
            </div>
          </div>
          <div style="display: flex; align-items: center; gap: 0.5rem; flex-shrink: 0">
            <input
              v-model.number="settings.brightness_default"
              type="number"
              class="form-input"
              min="0"
              max="100"
              style="width: 110px"
            />
            <span class="text-xs text-muted" style="width: 44px">%</span>
          </div>
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
const settings = ref({})

async function load() {
  try {
    settings.value = await apiFetch('/settings/agent')
  } catch {
    toast.add('Failed to load settings', 'error')
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const payload = {
      brightness_enabled: settings.value.brightness_enabled ? 1 : 0,
      brightness_default: Number(settings.value.brightness_default),
    }
    settings.value = await apiFetch('/settings/agent', {
      method: 'PUT',
      body: JSON.stringify(payload),
    })
    toast.add('Display settings saved', 'success')
  } catch (e) {
    toast.add(e.status === 422 ? 'Invalid value — check the ranges' : 'Failed to save settings', 'error')
  } finally {
    saving.value = false
  }
}

load()
</script>
