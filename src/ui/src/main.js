import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import { createPinia } from 'pinia'
import './custom.css'
import App from './App.vue'
import About from './About.vue'
import AuthCallback from './AuthCallback.vue'
import Login from './Login.vue'
import KioskList from './kiosks/KioskList.vue'
import KioskDetail from './kiosks/KioskDetail.vue'
import KioskEdit from './kiosks/KioskEdit.vue'
import KioskDebug from './kiosks/KioskDebug.vue'
import KioskCommandLog from './kiosks/KioskCommandLog.vue'
import PlaylistList from './playlists/PlaylistList.vue'
import PlaylistDetail from './playlists/PlaylistDetail.vue'
import UrlList from './urls/UrlList.vue'
import UrlEdit from './urls/UrlEdit.vue'
import SettingsIndex from './settings/SettingsIndex.vue'
import SettingsFeatureFlags from './settings/SettingsFeatureFlags.vue'
import SettingsAgents from './settings/SettingsAgents.vue'
import SettingsApiKeys from './settings/SettingsApiKeys.vue'
import SettingsTimingDefaults from './settings/SettingsTimingDefaults.vue'
import SettingsHosts from './settings/SettingsHosts.vue'
import SettingsBrowserFlags from './settings/SettingsBrowserFlags.vue'
import SettingsDefaultPage from './settings/SettingsDefaultPage.vue'
import SettingsCertificates from './settings/SettingsCertificates.vue'
import EventLog from './EventLog.vue'
import { isAuthenticated, login, AUTH_ENABLED } from './auth'


const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/callback', component: AuthCallback, meta: { public: true } },
    { path: '/login', component: Login, meta: { public: true } },
    { path: '/', component: KioskList, meta: { title: 'Kiosks' } },
    { path: '/kiosks/:id', component: KioskDetail, meta: { title: 'Kiosk' } },
    { path: '/kiosks/:id/edit', component: KioskEdit, meta: { title: 'Edit Kiosk' } },
    { path: '/kiosks/:id/debug', component: KioskDebug, meta: { title: 'Kiosk Debug' } },
    { path: '/kiosks/:id/log', component: KioskCommandLog, meta: { title: 'Event Log' } },
    { path: '/playlists', component: PlaylistList, meta: { title: 'Playlists' } },
    { path: '/playlists/:id', component: PlaylistDetail, meta: { title: 'Playlist' } },
    { path: '/urls', component: UrlList, meta: { title: 'Saved URLs' } },
    { path: '/urls/:id/edit', component: UrlEdit, meta: { title: 'Edit URL' } },
    { path: '/event-log', component: EventLog, meta: { title: 'Event Log' } },
    { path: '/settings', component: SettingsIndex, meta: { title: 'Settings' } },
    { path: '/settings/feature-flags', component: SettingsFeatureFlags, meta: { title: 'Feature Flags' } },
    { path: '/settings/agents', component: SettingsAgents, meta: { title: 'Agents' } },
    { path: '/settings/api-keys', component: SettingsApiKeys, meta: { title: 'API Keys' } },
    { path: '/settings/timing', component: SettingsTimingDefaults, meta: { title: 'Timing' } },
    { path: '/settings/hosts', component: SettingsHosts, meta: { title: 'Hosts' } },
    { path: '/settings/browser-flags', component: SettingsBrowserFlags, meta: { title: 'Browser Flags' } },
    { path: '/settings/default-page', component: SettingsDefaultPage, meta: { title: 'Default Page' } },
    { path: '/settings/certificates', component: SettingsCertificates, meta: { title: 'Certificates' } },
    { path: '/about', component: About, meta: { title: 'About' } },
  ],
})

router.beforeEach(async to => {
  if (to.meta.public) return true
  if (await isAuthenticated()) return true
  if (AUTH_ENABLED) {
    await login()
    return false
  }
  return { path: '/login' }
})

router.afterEach(to => {
  document.title = to.meta.title ? `kio — ${to.meta.title}` : 'kio'
})

const app = createApp(App)
app.use(createPinia())
app.use(router)
router.isReady().then(() => app.mount('#app'))
