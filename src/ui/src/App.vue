<template>
  <!-- Public routes (login, callback) render bare — no shell, no API calls -->
  <RouterView v-if="route.meta.public" />

  <div v-else :class="['app-shell', { 'has-env-banner': kioBranch || isLocal, 'sidebar-collapsed': collapsed }]">
    <div v-if="kioBranch" class="env-banner">
      STAGING &mdash; <code class="env-banner-branch">{{ kioBranch }}</code>
    </div>
    <div v-else-if="isLocal" class="env-banner env-banner-local">
      LOCAL
    </div>
    <aside class="sidebar">
      <div class="sidebar-header">
        <div class="sidebar-brand">
          <span class="brand-dot"></span>
          <span class="brand-text">kio</span>
        </div>
        <button class="sidebar-toggle" @click="collapsed = !collapsed" :title="collapsed ? 'Expand sidebar' : 'Collapse sidebar'">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <path v-if="!collapsed" d="M9 2L4 7l5 5"/>
            <path v-else d="M5 2l5 5-5 5"/>
          </svg>
        </button>
      </div>
      <nav class="sidebar-nav">
        <RouterLink to="/" :class="{ 'router-link-active': isKiosksActive }">
          <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="2" y="3" width="20" height="14" rx="2"/>
            <path d="M8 21h8M12 17v4"/>
          </svg>
          <span class="nav-label">Kiosks</span>
        </RouterLink>
        <RouterLink to="/urls" :class="{ 'router-link-active': isUrlsActive }">
          <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"/>
            <path d="M2 12h20"/>
            <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
          </svg>
          <span class="nav-label">URLs</span>
        </RouterLink>
        <RouterLink v-if="featureFlags.isEnabled('playlists')" to="/playlists" :class="{ 'router-link-active': isPlaylistsActive }">
          <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 5h12M3 9h9M3 13h6"/>
            <path d="M16 12l5 3-5 3v-6z"/>
          </svg>
          <span class="nav-label">Playlists</span>
        </RouterLink>
        <RouterLink to="/event-log">
          <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
          </svg>
          <span class="nav-label">Event Log</span>
        </RouterLink>
      </nav>
    </aside>

    <div class="main-wrapper">
      <header class="topbar">
        <div class="topbar-right">
          <div class="topbar-menu-wrapper">
            <button class="topbar-menu-btn" @click.stop="menuOpen = !menuOpen" :class="{ active: menuOpen }">
              <svg width="15" height="15" viewBox="0 0 15 15" fill="currentColor">
                <circle cx="7.5" cy="1.5" r="1.5"/>
                <circle cx="7.5" cy="7.5" r="1.5"/>
                <circle cx="7.5" cy="13.5" r="1.5"/>
              </svg>
            </button>
            <Transition name="dropdown">
              <div v-if="menuOpen" class="topbar-dropdown">
                <RouterLink to="/settings" @click="menuOpen = false">Settings</RouterLink>
                <RouterLink to="/about" @click="menuOpen = false">About</RouterLink>
                <button v-if="authActive" class="dropdown-logout" @click="handleLogout">Sign out</button>
                <div v-if="version" class="dropdown-version">{{ version }}</div>
              </div>
            </Transition>
          </div>
        </div>
      </header>

      <main class="main-content">
        <RouterView />
      </main>
    </div>

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
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { useToastStore } from './stores/toast'
import { useFeatureFlagsStore } from './stores/featureFlags'
import { useApi } from './composables/useApi'
import { logout, isAuthenticated, AUTH_ENABLED } from './auth'
import { KIO_BRANCH, IS_LOCAL } from './config'

const kioBranch = KIO_BRANCH
const isLocal = IS_LOCAL
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
const collapsed = ref(localStorage.getItem('sidebar-collapsed') === 'true')
const menuOpen = ref(false)

watch(collapsed, val => localStorage.setItem('sidebar-collapsed', String(val)))

function handleOutsideClick(e) {
  if (menuOpen.value && !e.target.closest('.topbar-menu-wrapper')) {
    menuOpen.value = false
  }
}

onMounted(async () => {
  if (route.meta.public) return
  authActive.value = AUTH_ENABLED || await isAuthenticated()
  try {
    const data = await apiFetch('/_version')
    version.value = data.version
  } catch {}
  featureFlags.load()
  document.addEventListener('click', handleOutsideClick)
})

onUnmounted(() => {
  document.removeEventListener('click', handleOutsideClick)
})

async function handleLogout() {
  menuOpen.value = false
  await logout()
  if (!AUTH_ENABLED) router.push('/login')
}
</script>
