<template>
  <!-- Public routes (login, callback) render bare — no shell, no API calls -->
  <RouterView v-if="route.meta.public" />

  <div v-else :class="['app-shell', { 'has-env-banner': kioBranch }]">
    <div v-if="kioBranch" class="env-banner">
      STAGING &mdash; <code class="env-banner-branch">{{ kioBranch }}</code>
    </div>
    <aside class="sidebar">
      <div class="sidebar-brand">
        <span class="brand-dot"></span>
        kio
      </div>
      <nav class="sidebar-nav">
        <RouterLink to="/" :class="{ 'router-link-active': isKiosksActive }">Kiosks</RouterLink>
        <RouterLink to="/urls" :class="{ 'router-link-active': isUrlsActive }">URLs</RouterLink>
        <RouterLink v-if="featureFlags.isEnabled('playlists')" to="/playlists" :class="{ 'router-link-active': isPlaylistsActive }">Playlists</RouterLink>
        <RouterLink to="/event-log">Event Log</RouterLink>
      </nav>
      <nav class="sidebar-nav sidebar-nav-bottom">
        <RouterLink to="/settings">Settings</RouterLink>
        <RouterLink to="/about">About</RouterLink>
        <button v-if="authActive" class="sidebar-logout" @click="handleLogout">Sign out</button>
        <span v-if="version" class="sidebar-version">{{ version }}</span>
      </nav>
    </aside>

    <main class="main-content">
      <RouterView />
    </main>

    <div class="toast-container">
      <div
        v-for="toast in toastStore.toasts"
        :key="toast.id"
        class="toast"
        :class="`toast-${toast.type}`"
      >
        {{ toast.message }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { useToastStore } from './stores/toast'
import { useFeatureFlagsStore } from './stores/featureFlags'
import { useApi } from './composables/useApi'
import { logout, isAuthenticated, AUTH_ENABLED } from './auth'
import { KIO_BRANCH } from './config'

const kioBranch = KIO_BRANCH
const toastStore = useToastStore()
const featureFlags = useFeatureFlagsStore()
const route = useRoute()
const router = useRouter()
const isKiosksActive = computed(() => route.path === '/' || route.path.startsWith('/kiosks'))
const isPlaylistsActive = computed(() => route.path.startsWith('/playlists'))
const isUrlsActive = computed(() => route.path.startsWith('/urls'))

const { apiFetch } = useApi()
const version = ref(null)
const authActive = ref(false)

onMounted(async () => {
  if (route.meta.public) return
  authActive.value = AUTH_ENABLED || await isAuthenticated()
  try {
    const data = await apiFetch('/_version')
    version.value = data.version
  } catch {}
  featureFlags.load()
})

async function handleLogout() {
  await logout()
  if (!AUTH_ENABLED) router.push('/login')
}
</script>
