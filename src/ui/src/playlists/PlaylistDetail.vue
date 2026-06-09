<template>
  <div>
    <div class="page-header">
      <div>
        <RouterLink to="/playlists" class="text-muted text-sm" style="display: inline-flex; align-items: center; gap: 4px; margin-bottom: 0.4rem">
          ← Playlists
        </RouterLink>
        <div style="display: flex; align-items: center; gap: var(--space-sm)">
          <h1 v-if="!editingName" class="page-title" style="cursor: pointer" @click="startEditName">
            {{ playlist.name }}
          </h1>
          <input
            v-else
            ref="nameInput"
            v-model="playlist.name"
            class="form-input page-title"
            style="width: auto; font-size: 1.4rem; font-weight: 700; letter-spacing: -0.02em; padding: 0.1rem 0.4rem"
            @blur="commitName"
            @keyup.enter="commitName"
            @keyup.escape="cancelEditName"
          />
        </div>
        <p v-if="playlist.description" class="page-subtitle">{{ playlist.description }}</p>
      </div>
      <div style="display: flex; gap: var(--space-sm); align-items: center">
        <span v-if="dirty" class="text-muted text-sm">Unsaved changes</span>
        <button class="btn btn-secondary" @click="load">Discard</button>
        <button class="btn btn-primary" :disabled="saving" @click="save">
          {{ saving ? 'Saving…' : 'Save' }}
        </button>
      </div>
    </div>

    <div v-if="loading" class="text-muted text-sm">Loading…</div>

    <template v-else>
      <!-- Playback settings -->
      <div class="card mb-lg">
        <div class="card-header">Playback Settings</div>
        <div style="display: flex; align-items: flex-end; gap: 0.75rem; flex-wrap: wrap">
          <div>
            <label class="form-label">Refresh interval (seconds)</label>
            <input
              v-model.number="playlist.refresh_interval_seconds"
              class="form-input"
              type="number"
              min="0"
              style="width: 160px"
              @input="dirty = true"
            />
          </div>
          <p class="text-xs text-muted" style="margin: 0 0 0.5rem; max-width: 420px">
            How often the agent reloads each page in the background to keep content fresh.
            <strong>0 disables refreshing</strong> — pages load once at start and aren't reloaded.
            Refreshes are jittered and happen while a tab is hidden, so they don't all reload at
            once or flash the screen.
          </p>
        </div>
      </div>

      <!-- Items -->
      <div class="card" style="padding: 0; overflow: hidden">
        <div class="card-header" style="padding: var(--space-md) var(--space-lg); margin: 0">
          URLs — {{ items.length }} {{ items.length === 1 ? 'item' : 'items' }}
        </div>

        <div v-if="items.length === 0" class="empty-state" style="padding: 2.5rem 0">
          No URLs yet — add one below.
        </div>

        <div v-else>
          <div
            v-for="(item, idx) in items"
            :key="item._key"
            class="playlist-item"
            :class="{ 'drag-over': dragOver === idx }"
            draggable="true"
            @dragstart="onDragStart(idx)"
            @dragover.prevent="onDragOver(idx)"
            @drop.prevent="onDrop(idx)"
            @dragend="onDragEnd"
          >
            <div class="drag-handle" title="Drag to reorder">⠿</div>

            <span class="item-index text-muted text-xs">{{ idx + 1 }}</span>

            <input
              v-model="item.title"
              class="form-input"
              placeholder="Title"
              style="width: 180px; flex-shrink: 0"
              @input="dirty = true"
            />
            <UrlTypeahead
              :model-value="item.url"
              placeholder="https://example.com"
              style="flex: 1"
              @update:model-value="val => { item.url = val; dirty = true }"
            />

            <div style="display: flex; align-items: center; gap: var(--space-xs); flex-shrink: 0">
              <input
                v-model.number="item.duration_seconds"
                class="form-input"
                type="number"
                min="1"
                style="width: 72px; text-align: right"
                @input="dirty = true"
              />
              <span class="text-muted text-sm" style="white-space: nowrap">sec</span>
            </div>

            <button class="btn btn-ghost" style="color: var(--danger); flex-shrink: 0" @click="removeItem(idx)">✕</button>
          </div>
        </div>

        <div style="padding: var(--space-md) var(--space-lg); border-top: 1px solid var(--border-subtle)">
          <button class="btn btn-secondary" @click="addItem">+ Add URL</button>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, nextTick, watch } from 'vue'
import { useRoute, RouterLink } from 'vue-router'
import { useApi } from '../composables/useApi'
import { useToastStore } from '../stores/toast'
import UrlTypeahead from '../urls/UrlTypeahead.vue'

const route = useRoute()
const { apiFetch } = useApi()
const toast = useToastStore()

const loading = ref(true)
const saving = ref(false)
const dirty = ref(false)
const playlist = ref({ name: '', description: '', refresh_interval_seconds: 0 })
const items = ref([])
const editingName = ref(false)
const nameInput = ref(null)
let savedName = ''

// drag state
const dragFrom = ref(null)
const dragOver = ref(null)

let keyCounter = 0
function makeKey() { return ++keyCounter }

async function load() {
  loading.value = true
  dirty.value = false
  try {
    const data = await apiFetch(`/playlists/${route.params.id}`)
    playlist.value = {
      name: data.name,
      description: data.description ?? '',
      refresh_interval_seconds: data.refresh_interval_seconds ?? 0,
    }
    savedName = data.name
    items.value = (data.items ?? []).map(it => ({ ...it, _key: makeKey() }))
  } catch {
    toast.add('Failed to load playlist', 'error')
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    await apiFetch(`/playlists/${route.params.id}`, {
      method: 'PUT',
      body: JSON.stringify({
        name: playlist.value.name,
        description: playlist.value.description || null,
        refresh_interval_seconds: Math.max(0, playlist.value.refresh_interval_seconds || 0),
        items: items.value.map((it, i) => ({
          title: it.title || null,
          url: it.url,
          duration_seconds: it.duration_seconds,
          position: i + 1,
        })),
      }),
    })
    savedName = playlist.value.name
    dirty.value = false
    toast.add('Playlist saved', 'success')
  } catch {
    toast.add('Failed to save playlist', 'error')
  } finally {
    saving.value = false
  }
}

function addItem() {
  items.value.push({ url: '', duration_seconds: 30, _key: makeKey() })
  dirty.value = true
}

function removeItem(idx) {
  items.value.splice(idx, 1)
  dirty.value = true
}

// Inline name editing
function startEditName() {
  savedName = playlist.value.name
  editingName.value = true
  nextTick(() => nameInput.value?.select())
}

function commitName() {
  if (!playlist.value.name.trim()) {
    playlist.value.name = savedName
  } else {
    dirty.value = true
  }
  editingName.value = false
}

function cancelEditName() {
  playlist.value.name = savedName
  editingName.value = false
}

// Drag-to-reorder
function onDragStart(idx) { dragFrom.value = idx }
function onDragOver(idx) { dragOver.value = idx }
function onDragEnd() { dragFrom.value = null; dragOver.value = null }

function onDrop(toIdx) {
  const fromIdx = dragFrom.value
  if (fromIdx === null || fromIdx === toIdx) return
  const moved = items.value.splice(fromIdx, 1)[0]
  items.value.splice(toIdx, 0, moved)
  dirty.value = true
  dragFrom.value = null
  dragOver.value = null
}

load()
</script>

<style scoped>
.playlist-item {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: 0.6rem var(--space-lg);
  border-bottom: 1px solid var(--border-subtle);
  transition: background var(--transition);
}

.playlist-item:last-child { border-bottom: none; }

.playlist-item:hover { background: var(--bg-surface-hover); }

.playlist-item.drag-over { background: var(--bg-surface-elevated); outline: 1px solid var(--accent); }

.drag-handle {
  color: var(--text-dim);
  cursor: grab;
  font-size: 1.1rem;
  line-height: 1;
  user-select: none;
  flex-shrink: 0;
}

.drag-handle:active { cursor: grabbing; }

.item-index {
  width: 1.4rem;
  text-align: right;
  flex-shrink: 0;
}
</style>
