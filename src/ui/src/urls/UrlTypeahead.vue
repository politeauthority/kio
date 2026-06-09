<template>
  <div style="position: relative">
    <input
      ref="inputEl"
      :value="modelValue"
      :type="inputType"
      :placeholder="placeholder"
      :required="required"
      :disabled="disabled"
      class="form-input"
      autocomplete="off"
      @input="onInput"
      @keydown="onKeydown"
      @focus="onFocus"
      @blur="onBlur"
    />
    <div
      v-if="showDropdown && suggestions.length > 0"
      class="url-typeahead-dropdown"
    >
      <div
        v-for="(item, i) in suggestions"
        :key="item.id"
        class="url-typeahead-item"
        :class="{ 'url-typeahead-item--active': i === activeIndex }"
        @mousedown.prevent="select(item)"
      >
        <div class="url-typeahead-name">{{ item.name }}</div>
        <div class="url-typeahead-url">{{ item.url }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useApi } from '../composables/useApi'

const props = defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: 'https://example.com' },
  required: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  inputType: { type: String, default: 'text' },
})

const emit = defineEmits(['update:modelValue'])

const { apiFetch } = useApi()
const inputEl = ref(null)
const suggestions = ref([])
const showDropdown = ref(false)
const activeIndex = ref(-1)
let debounceTimer = null

async function fetchSuggestions(q) {
  try {
    const params = q ? `?q=${encodeURIComponent(q)}` : ''
    suggestions.value = await apiFetch(`/saved-urls${params}`)
  } catch {
    suggestions.value = []
  }
}

function onInput(e) {
  const val = e.target.value
  emit('update:modelValue', val)
  activeIndex.value = -1
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => fetchSuggestions(val), 200)
}

async function onFocus() {
  await fetchSuggestions(props.modelValue)
  showDropdown.value = true
}

function onBlur() {
  setTimeout(() => { showDropdown.value = false }, 150)
}

function select(item) {
  emit('update:modelValue', item.url)
  showDropdown.value = false
  suggestions.value = []
}

function onKeydown(e) {
  if (!showDropdown.value || suggestions.value.length === 0) return
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    activeIndex.value = Math.min(activeIndex.value + 1, suggestions.value.length - 1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    activeIndex.value = Math.max(activeIndex.value - 1, -1)
  } else if (e.key === 'Enter' && activeIndex.value >= 0) {
    e.preventDefault()
    select(suggestions.value[activeIndex.value])
  } else if (e.key === 'Escape') {
    showDropdown.value = false
  }
}

watch(() => props.modelValue, (val) => {
  if (document.activeElement !== inputEl.value) return
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => fetchSuggestions(val), 200)
})
</script>

<style scoped>
.url-typeahead-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  background: var(--bg-card, #1e1e2e);
  border: 1px solid var(--border, #3a3a4a);
  border-radius: var(--radius, 6px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
  z-index: 100;
  max-height: 260px;
  overflow-y: auto;
}

.url-typeahead-item {
  padding: 0.5rem 0.75rem;
  cursor: pointer;
  border-bottom: 1px solid var(--border, #3a3a4a);
}

.url-typeahead-item:last-child {
  border-bottom: none;
}

.url-typeahead-item:hover,
.url-typeahead-item--active {
  background: var(--accent-subtle, rgba(99, 102, 241, 0.12));
}

.url-typeahead-name {
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--text, #e0e0f0);
}

.url-typeahead-url {
  font-size: 0.75rem;
  color: var(--text-muted, #8888aa);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
