<template>
  <div>
    <div class="page-header">
      <h1 class="page-title">Settings</h1>
    </div>

    <div style="display: flex; flex-direction: column; gap: var(--space-xl)">
      <!-- System Settings -->
      <div>
        <h2 class="text-sm" style="font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-muted); margin-bottom: var(--space-md)">
          System Settings
        </h2>
        <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: var(--space-md)">
          <RouterLink
            v-for="item in systemItems"
            :key="item.to"
            :to="item.to"
            class="settings-card"
          >
            <div class="settings-card-title">{{ item.title }}</div>
            <div class="settings-card-desc">{{ item.description }}</div>
          </RouterLink>
        </div>
      </div>

      <!-- Node Settings -->
      <div>
        <h2 class="text-sm" style="font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-muted); margin-bottom: var(--space-md)">
          Node Settings
        </h2>
        <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: var(--space-md)">
          <RouterLink
            v-for="item in nodeItems"
            :key="item.to"
            :to="item.to"
            class="settings-card"
          >
            <div class="settings-card-title">{{ item.title }}</div>
            <div class="settings-card-desc">{{ item.description }}</div>
          </RouterLink>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { useFeatureFlagsStore } from '../stores/featureFlags'

const flagStore = useFeatureFlagsStore()

const systemItems = [
  {
    to: '/settings/feature-flags',
    title: 'Feature Flags',
    description: 'Enable or disable UI features across the dashboard.',
  },
  {
    to: '/settings/agents',
    title: 'Agents',
    description: 'System-wide agent health and retention settings.',
  },
  {
    to: '/settings/api-keys',
    title: 'API Keys',
    description: 'Manage programmatic access keys for integrations.',
  },
]

const nodeItems = computed(() => {
  const items = [
    {
      to: '/settings/timing',
      title: 'Timing',
      description: 'Default heartbeat and checkin intervals applied to all nodes.',
    },
    {
      to: '/settings/hosts',
      title: 'Hosts',
      description: 'Global /etc/hosts entries injected into every node at startup.',
    },
    {
      to: '/settings/browser-flags',
      title: 'Browser Flags',
      description: 'Default Chromium flags applied to all nodes.',
    },
  ]
  if (flagStore.isEnabled('import_certs')) {
    items.push({
      to: '/settings/certificates',
      title: 'Certificates',
      description: 'CA certificates synced to every node so Chromium trusts internal HTTPS services.',
    })
  }
  return items
})
</script>

<style scoped>
.settings-card {
  display: block;
  padding: var(--space-lg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-card);
  text-decoration: none;
  color: inherit;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.settings-card:hover {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent);
}
.settings-card-title {
  font-weight: 600;
  font-size: 0.95rem;
  margin-bottom: 0.35rem;
  color: var(--text-primary);
}
.settings-card-desc {
  font-size: 0.8rem;
  color: var(--text-muted);
  line-height: 1.4;
}
</style>
