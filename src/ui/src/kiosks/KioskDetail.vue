<template>
  <div v-if="kiosk">
    <div class="page-header">
      <div>
        <RouterLink to="/" class="text-muted text-sm">← All Kiosks</RouterLink>
        <h1 class="page-title mt-sm">{{ kiosk.name }}</h1>
        <p class="page-subtitle"><code>{{ kiosk.hostname }}</code></p>
        <div
          v-if="playlistPlaying"
          class="text-xs"
          style="display: inline-flex; align-items: center; gap: 0.4rem; margin-top: 0.5rem; padding: 0.2rem 0.6rem; border-radius: var(--radius-sm); background: var(--accent-subtle, rgba(99,102,241,0.12)); color: var(--accent)"
        >
          <span style="font-size: 0.7rem">●</span>
          Playing playlist<span v-if="attachedPlaylist"> — {{ attachedPlaylist.name }}</span>
        </div>
      </div>
      <div class="d-flex gap-sm">
        <RouterLink v-if="featureFlags.isEnabled('debug')" :to="`/kiosks/${kioskId}/debug`" class="btn btn-ghost text-sm">Debug</RouterLink>
        <RouterLink :to="`/kiosks/${kioskId}/edit`" class="btn btn-secondary">Edit</RouterLink>
      </div>
    </div>

    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; align-items: start">

      <!-- Status card -->
      <div class="card">
        <div class="card-header">Status</div>
        <div style="display: flex; flex-direction: column; gap: 1rem">
          <div>
            <div class="text-xs text-muted" style="margin-bottom: 4px">STATUS</div>
            <span class="status-badge" :class="`status-${liveStatus}`">{{ liveStatus }}</span>
          </div>
          <div v-if="kiosk.device_type">
            <div class="text-xs text-muted" style="margin-bottom: 4px">MODEL</div>
            <span class="text-sm">{{ kiosk.device_type }}</span>
          </div>
          <div v-if="kiosk.ip_address">
            <div class="text-xs text-muted" style="margin-bottom: 4px">IP ADDRESS</div>
            <code class="text-sm">{{ kiosk.ip_address }}</code>
          </div>
          <div v-if="kiosk.agent_version">
            <div class="text-xs text-muted" style="margin-bottom: 4px">AGENT VERSION</div>
            <div style="display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap">
              <span class="text-sm">{{ kiosk.agent_version }}</span>
              <span
                v-if="agentOutdated"
                class="text-xs"
                style="padding: 0.1rem 0.45rem; border-radius: var(--radius-sm); white-space: nowrap; background: color-mix(in srgb, var(--warning) 18%, transparent); color: var(--warning)"
              >update available</span>
              <button
                v-if="agentOutdated"
                class="btn btn-secondary"
                style="padding: 0.15rem 0.55rem; font-size: 0.75rem"
                :disabled="commandsBlocked"
                @click="showUpdateModal = true"
              >Update agent</button>
            </div>
            <div v-if="agentOutdated" class="text-xs text-muted" style="margin-top: 3px">latest: {{ latestAgentVersion }}</div>
          </div>
          <div>
            <div class="text-xs text-muted" style="margin-bottom: 4px">LAST SEEN</div>
            <span class="text-sm text-muted">{{ formatLastSeen(kiosk.last_seen) }}</span>
          </div>
          <div>
            <div class="text-xs text-muted" style="margin-bottom: 4px">UPTIME</div>
            <span class="text-sm" :class="uptimeDisplay === 'Unknown' ? 'text-muted' : ''">{{ uptimeDisplay }}</span>
          </div>
        </div>
      </div>

      <!-- Command panel -->
      <div class="card">
        <div class="card-header">Commands</div>

        <!-- Display controls (inline, when any are visible) -->
        <template v-if="visibleControls.length">
          <div style="display: flex; flex-wrap: wrap; gap: 1.25rem; margin-bottom: 1rem">

            <div v-if="kiosk.features.includes('display_power') && !hiddenControls.has('display_power')">
              <div class="text-xs text-muted" style="margin-bottom: 0.5rem">DISPLAY POWER</div>
              <button
                v-if="liveDisplayOn === true"
                class="btn btn-secondary"
                :disabled="commandsBlocked"
                @click="sendDisplayCommand('display_off', false)"
              >Turn Off</button>
              <button
                v-else-if="liveDisplayOn === false"
                class="btn btn-primary"
                :disabled="commandsBlocked"
                @click="sendDisplayCommand('display_on', true)"
              >Turn On</button>
              <div v-else class="d-flex gap-sm">
                <button class="btn btn-secondary" :disabled="commandsBlocked" @click="sendDisplayCommand('display_on', true)">On</button>
                <button class="btn btn-secondary" :disabled="commandsBlocked" @click="sendDisplayCommand('display_off', false)">Off</button>
              </div>
            </div>

            <div v-if="kiosk.features.includes('cec') && !hiddenControls.has('cec')">
              <div class="text-xs text-muted" style="margin-bottom: 0.5rem">CEC</div>
              <div class="d-flex gap-sm">
                <button class="btn btn-secondary" :disabled="commandsBlocked" @click="sendCommand('wake')">Wake</button>
                <button class="btn btn-secondary" :disabled="commandsBlocked" @click="sendCommand('standby')">Standby</button>
              </div>
            </div>

            <div v-if="kiosk.features.includes('input_switch') && !hiddenControls.has('input_switch')">
              <div class="text-xs text-muted" style="margin-bottom: 0.5rem">INPUT</div>
              <div class="d-flex gap-sm">
                <button
                  v-for="inp in INPUTS"
                  :key="inp.value"
                  class="btn"
                  :class="liveInput === inp.value ? 'btn-primary' : 'btn-secondary'"
                  :disabled="commandsBlocked"
                  @click="sendInput(inp.value)"
                >{{ inp.label }}</button>
              </div>
              <div v-if="!liveInput" class="text-xs text-muted" style="margin-top: 0.4rem">
                Active input unknown — reported on next hourly heartbeat
              </div>
            </div>

            <div v-if="kiosk.features.includes('brightness') && !hiddenControls.has('brightness')">
              <div class="text-xs text-muted" style="margin-bottom: 0.5rem">BRIGHTNESS</div>
              <div class="d-flex gap-sm" style="align-items: center">
                <input
                  type="range" min="0" max="100" step="5"
                  v-model.number="liveBrightness"
                  :disabled="commandsBlocked"
                  @change="sendBrightness(liveBrightness)"
                  style="flex: 1"
                />
                <span class="text-xs text-muted" style="width: 36px; text-align: right">{{ liveBrightness }}%</span>
              </div>
            </div>

          </div>
          <hr style="border-color: var(--border); margin: 1rem 0" />
        </template>

        <!-- Navigate to URL — temporarily hidden -->
        <!-- <form @submit.prevent="sendNav" style="display: flex; gap: 0.5rem; align-items: flex-end; margin-bottom: 0.5rem">
          <div style="flex: 1">
            <label class="form-label">Navigate to URL</label>
            <UrlTypeahead v-model="urlInput" placeholder="https://example.com" :required="true" />
          </div>
          <button type="submit" class="btn btn-primary" :disabled="commandsBlocked">Go</button>
        </form>
        <p v-if="playlistPlaying" class="text-xs" style="margin: 0 0 1rem; color: var(--warning)">
          ⚠ A playlist is running — navigating to a URL or focusing a tab will stop it.
        </p>

        <hr style="border-color: var(--border); margin: 1rem 0" /> -->

        <!-- Page control — temporarily hidden -->
        <!-- <div class="text-xs text-muted" style="margin-bottom: 0.5rem">PAGE CONTROL</div>
        <button class="btn btn-secondary" :disabled="commandsBlocked" @click="sendCommand('reload')">↺ Reload</button>

        <hr style="border-color: var(--border); margin: 1rem 0" /> -->

        <div class="text-xs text-muted" style="margin-bottom: 0.5rem">SYSTEM</div>
        <button class="btn btn-danger" :disabled="commandsBlocked" @click="showRebootModal = true">Reboot</button>

      </div>
    </div>

    <!-- Browser Tabs card -->
    <div class="card mt-lg">
      <div class="card-header" style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0; gap: 0.5rem; flex-wrap: wrap">
        <span>Browser Tabs</span>
        <div style="display: flex; align-items: center; gap: 0.5rem">
          <span class="text-xs text-muted">{{ displayTabs.length }} tab{{ displayTabs.length === 1 ? '' : 's' }}</span>
          <!-- Tab cycling controls — hidden while a playlist is actively playing,
               since a playlist already drives the rotation. -->
          <template v-if="!playlistPlaying">
            <button class="btn btn-ghost" style="padding: 0.2rem 0.6rem; font-size: 0.8rem" @click="openCycleModal" title="Tab cycling settings">⟳ Cycle</button>
            <button
              v-if="tabCyclePlaying"
              class="btn btn-secondary"
              style="padding: 0.2rem 0.6rem; font-size: 0.8rem"
              :disabled="commandsBlocked"
              @click="stopTabCycle"
            >■ Stop</button>
            <button
              v-else-if="tabCycleEnabled"
              class="btn btn-primary"
              style="padding: 0.2rem 0.6rem; font-size: 0.8rem"
              :disabled="commandsBlocked"
              @click="startTabCycle"
            >▶ Start</button>
          </template>
        </div>
      </div>

      <!-- Rough cycle estimate: full loop ≈ interval × open tabs. -->
      <div v-if="!playlistPlaying && tabCycleEnabled && cycleTabCount" class="text-xs text-muted" style="margin-top: 0.6rem">
        <span v-if="tabCyclePlaying" style="color: var(--accent)">● Cycling</span><span v-else>Cycle ready</span>
        — every {{ cycleIntervalSeconds }}s, full loop ≈ {{ fmtCycleEstimate(fullCycleSeconds) }}
        ({{ cycleTabCount }} tab{{ cycleTabCount === 1 ? '' : 's' }})
      </div>

      <div v-if="displayTabs.length === 0" class="text-muted text-sm" style="margin-top: 0.75rem">
        No open tabs — kiosk may be offline or CDP unavailable.
      </div>

      <div v-else style="display: flex; flex-direction: column; gap: 0.5rem; margin-top: 0.75rem">
        <div
          v-for="tab in displayTabs"
          :key="tab.id"
          style="display: flex; align-items: center; gap: 0.5rem; padding: 0.5rem 0.75rem; border-radius: var(--radius); border: 1px solid var(--border)"
          :style="isTabActive(tab)
            ? 'background: var(--accent-subtle, rgba(99,102,241,0.12)); border-color: var(--accent)'
            : 'background: var(--bg-dark)'"
          @dragover.prevent
          @drop="onTabDrop(tab)"
        >
          <!-- Drag handle: reorders the tab list (and the cycle sequence). Real tabs
               only — pending placeholders have no stable URL to order by yet. -->
          <span
            v-if="!tab.pending"
            draggable="true"
            @dragstart="onTabDragStart(tab)"
            class="text-muted"
            style="cursor: grab; user-select: none; font-size: 0.9rem; line-height: 1; flex-shrink: 0"
            title="Drag to reorder"
          >⠿</span>
          <div style="flex: 1; min-width: 0">
            <div class="text-sm" style="font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis">
              {{ savedUrlFor(tab.url)?.name || tab.title || (tab.pending ? 'Opening…' : '(no title)') }}
            </div>
            <div class="text-xs text-muted" style="display: flex; align-items: center; gap: 0.4rem; min-width: 0" :title="tab.url">
              <span v-if="tab.http_status" :style="statusBadgeStyle(tab.http_status)">{{ tab.http_status }}</span>
              <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0">{{ truncateUrl(tab.url) }}</span>
            </div>
            <div v-if="!tab.pending && pendingRefreshTabs[tab.id]" class="text-xs text-muted" style="margin-top: 2px; display: flex; align-items: center; gap: 0.4rem">
              <span class="kio-spinner" style="width: 0.7rem; height: 0.7rem"></span>
              refreshing…
            </div>
            <div v-else-if="!tab.pending && tab.age_seconds != null" class="text-xs text-muted" style="margin-top: 2px">
              refreshed {{ fmtAge(tabAge(tab)) }} ago
            </div>
          </div>
          <div class="d-flex gap-sm" style="flex-shrink: 0; align-items: center">
            <template v-if="tab.pending">
              <span class="kio-spinner" style="width: 0.9rem; height: 0.9rem"></span>
              <span class="text-xs text-muted" style="white-space: nowrap">waiting for node…</span>
            </template>
            <template v-else>
              <span v-if="tab.id === pendingFocusTabId" style="display: flex; align-items: center; gap: 0.4rem; color: var(--text-muted); font-size: 0.7rem; white-space: nowrap; margin-right: 0.25rem">
                <span class="kio-spinner" style="width: 0.75rem; height: 0.75rem"></span>
                focusing…
              </span>
              <span v-else-if="isTabActive(tab)" style="color: var(--accent); font-size: 0.7rem; white-space: nowrap; margin-right: 0.25rem">● ON SCREEN</span>
              <RouterLink v-if="savedUrlFor(tab.url)" :to="`/urls/${savedUrlFor(tab.url).id}/edit`" class="btn btn-ghost" style="padding: 0.2rem 0.5rem; font-size: 0.8rem; color: var(--text-muted)">Edit URL</RouterLink>
              <button class="btn btn-secondary" style="padding: 0.2rem 0.6rem; font-size: 0.8rem" :disabled="commandsBlocked" @click="activateTab(tab.id)">Focus</button>
              <button class="btn btn-secondary" style="padding: 0.2rem 0.6rem; font-size: 0.8rem" :disabled="commandsBlocked" @click="refreshTab(tab.id)">↻ Refresh</button>
              <button class="btn btn-ghost" style="padding: 0.2rem 0.6rem; font-size: 0.8rem; color: var(--danger)" :disabled="commandsBlocked" @click="closeTab(tab.id)" title="Close tab (or reset to default if it's the last one)">✕</button>
            </template>
          </div>
        </div>
      </div>

      <!-- Open new tab -->
      <form @submit.prevent="openNewTab" style="display: flex; gap: 0.5rem; align-items: flex-end; margin-top: 1rem; padding-top: 0.75rem; border-top: 1px solid var(--border)">
        <div style="flex: 1">
          <label class="form-label">Open new tab</label>
          <UrlTypeahead v-model="newTabUrl" placeholder="https://example.com" :required="true" />
        </div>
        <button type="submit" class="btn btn-secondary" :disabled="commandsBlocked">Open</button>
      </form>
    </div>

    <!-- Playlist panel -->
    <div v-if="featureFlags.isEnabled('playlists')" class="card mt-lg">
      <div class="card-header" style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0">
        <span>Playlist</span>
        <div v-if="attachedPlaylist" class="d-flex gap-sm">
          <button
            v-if="playlistPlaying"
            class="btn btn-secondary"
            :disabled="commandsBlocked"
            @click="stopPlaylist"
          >■ Stop</button>
          <button
            v-else
            class="btn btn-primary"
            :disabled="commandsBlocked"
            @click="playPlaylist"
          >▶ Play</button>
        </div>
      </div>

      <div v-if="attachedPlaylist" style="margin-top: 1rem">
        <div style="display: flex; align-items: center; justify-content: space-between">
          <div>
            <RouterLink :to="`/playlists/${attachedPlaylist.id}`" class="text-sm" style="font-weight: 500">
              {{ attachedPlaylist.name }}
            </RouterLink>
            <span class="text-xs text-muted" style="margin-left: 0.5rem">{{ attachedPlaylistItems.length || attachedPlaylist.item_count || '?' }} URLs</span>
          </div>
          <div class="d-flex gap-sm">
            <button class="btn btn-ghost text-sm" @click="showChangePlaylist = !showChangePlaylist">Change</button>
            <button class="btn btn-ghost text-sm" style="color: var(--danger)" @click="detachPlaylist">Detach</button>
          </div>
        </div>

        <!-- Change playlist selector -->
        <div v-if="showChangePlaylist" style="display: flex; gap: 0.5rem; align-items: center; margin-top: 0.75rem">
          <select v-model="selectedPlaylistId" class="form-input" style="flex: 1">
            <option value="">Select a playlist…</option>
            <option v-for="pl in availablePlaylists" :key="pl.id" :value="pl.id">{{ pl.name }}</option>
          </select>
          <button class="btn btn-secondary" :disabled="!selectedPlaylistId || commandsBlocked" @click="attachPlaylist">Attach</button>
          <button class="btn btn-ghost" @click="showChangePlaylist = false; selectedPlaylistId = ''">Cancel</button>
        </div>

        <div v-if="attachedPlaylistItems.length" style="margin-top: 0.75rem; display: flex; flex-direction: column; gap: 0.25rem">
          <div
            v-for="(item, idx) in attachedPlaylistItems"
            :key="item.id"
            style="display: flex; align-items: center; gap: 0.5rem; padding: 0.35rem 0.6rem; border-radius: var(--radius-sm); border: 1px solid var(--border)"
            :style="idx === playlistActiveIdx ? 'background: var(--accent-subtle, rgba(99,102,241,0.12)); border-color: var(--accent)' : 'background: var(--bg-dark)'"
          >
            <span class="text-xs text-muted" style="min-width: 1.25rem; text-align: right">{{ idx + 1 }}</span>
            <span class="text-sm" style="flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap" :title="item.url">
              {{ item.title || item.url }}
            </span>
            <!-- Countdown on the active item -->
            <span v-if="idx === playlistActiveIdx && playlistCountdown !== null" class="text-xs" style="color: var(--accent); white-space: nowrap; min-width: 3.5rem; text-align: right">
              next in {{ playlistCountdown }}s
            </span>
            <span v-else class="text-xs text-muted">{{ item.duration_seconds }}s</span>
            <button
              class="btn btn-ghost text-xs"
              style="padding: 0.15rem 0.5rem; min-width: 2rem"
              :disabled="commandsBlocked"
              title="Jump to this item"
              @click="gotoPlaylistItem(idx)"
            >→</button>
          </div>
        </div>
      </div>

      <div v-else style="margin-top: 1rem">
        <div v-if="availablePlaylists.length === 0" class="text-muted text-sm">No playlists — <RouterLink to="/playlists">create one</RouterLink> first.</div>
        <div v-else style="display: flex; gap: 0.5rem; align-items: center">
          <select v-model="selectedPlaylistId" class="form-input" style="flex: 1">
            <option value="">Select a playlist…</option>
            <option v-for="pl in availablePlaylists" :key="pl.id" :value="pl.id">{{ pl.name }}</option>
          </select>
          <button class="btn btn-secondary" :disabled="!selectedPlaylistId || commandsBlocked" @click="attachPlaylist">Attach</button>
        </div>
      </div>
    </div>

    <!-- File Permission Errors card -->
    <div v-if="filePermissionErrors.length" class="card mt-lg">
      <div class="card-header">File Permission Errors</div>
      <table class="table" style="margin-top: 0.5rem">
        <thead>
          <tr>
            <th>Time</th>
            <th>File</th>
            <th>Process</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(err, i) in filePermissionErrors" :key="i">
            <td class="text-xs text-muted" style="white-space: nowrap">{{ formatDate(err.at) }}</td>
            <td class="text-sm"><code>{{ err.file }}</code></td>
            <td class="text-xs text-muted">{{ err.process }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Event Log card -->
    <div class="card mt-lg">
      <div class="card-header" style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0">
        <span>Event Log</span>
        <RouterLink :to="`/kiosks/${kioskId}/log`" class="text-sm text-muted">View all →</RouterLink>
      </div>
      <div v-if="commandLog.length === 0" class="text-muted text-sm" style="margin-top: 0.5rem">
        No events recorded yet.
      </div>
      <table v-else class="table" style="margin-top: 0.5rem">
        <thead>
          <tr>
            <th>Time</th>
            <th>Event</th>
            <th>Source</th>
            <th>Result</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="entry in commandLog" :key="entry.id">
            <tr
              :class="{ 'row-expandable': !!entry.agent_message }"
              @click="entry.agent_message && toggleRow(entry.id)"
            >
              <td class="text-xs text-muted" style="white-space: nowrap">{{ formatDate(entry.sent_at) }}</td>
              <td class="text-sm"><code>{{ entry.command }}</code></td>
              <td class="text-xs text-muted">{{ entry.source }}</td>
              <td>
                <span class="result-cell">
                  <span v-if="entry.agent_success === null" class="text-muted text-xs">pending</span>
                  <span v-else-if="entry.agent_success" class="result-ok">✓</span>
                  <span v-else class="result-fail">✗</span>
                  <span v-if="entry.agent_message" class="expand-caret">{{ expandedRows.has(entry.id) ? '▲' : '▼' }}</span>
                </span>
              </td>
            </tr>
            <tr v-if="entry.agent_message && expandedRows.has(entry.id)" class="msg-detail-row">
              <td colspan="4"><pre class="msg-detail" :class="{ 'is-error': entry.agent_success === false }">{{ entry.agent_message }}</pre></td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>

  </div>

  <div v-else-if="loading" class="text-muted text-sm">Loading…</div>
  <div v-else class="empty-state">Kiosk not found.</div>

  <!-- Reboot confirmation modal -->
  <Teleport to="body">
    <div v-if="showRebootModal" class="modal-backdrop" @click.self="showRebootModal = false">
      <div class="modal-box">
        <h2 class="modal-title">Reboot {{ kiosk?.name }}?</h2>
        <p class="text-muted text-sm" style="margin: 0.75rem 0 1.5rem">
          The kiosk will go offline for ~30 seconds while it restarts.
        </p>
        <div class="d-flex gap-sm" style="justify-content: flex-end">
          <button class="btn btn-secondary" @click="showRebootModal = false">Cancel</button>
          <button class="btn btn-danger" @click="confirmReboot">Reboot</button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- Agent update confirmation modal -->
  <Teleport to="body">
    <div v-if="showUpdateModal" class="modal-backdrop" @click.self="showUpdateModal = false">
      <div class="modal-box">
        <h2 class="modal-title">Update {{ kiosk?.name }} agent?</h2>
        <p class="text-muted text-sm" style="margin: 0.75rem 0 1.5rem">
          The node will pull
          <code>{{ latestAgentVersion }}</code> from git and restart the agent
          (~30s offline). It's currently on <code>{{ kiosk?.agent_version }}</code>.
        </p>
        <div class="d-flex gap-sm" style="justify-content: flex-end">
          <button class="btn btn-secondary" @click="showUpdateModal = false">Cancel</button>
          <button class="btn btn-primary" :disabled="commanding" @click="confirmUpdateAgent">Update</button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- Tab cycling settings -->
  <Teleport to="body">
    <div v-if="showCycleModal" class="modal-backdrop" @click.self="showCycleModal = false">
      <div class="modal-box">
        <h2 class="modal-title">Tab cycling</h2>
        <p class="text-muted text-sm" style="margin: 0.75rem 0 1.25rem">
          Automatically rotate this node through its open browser tabs. Enable it to
          reveal the Start/Stop controls; drag tabs to set the rotation order.
        </p>
        <label class="d-flex gap-sm" style="align-items: center; margin-bottom: 1rem; cursor: pointer">
          <input type="checkbox" v-model="cycleForm.enabled" />
          <span class="text-sm">Enable tab cycling</span>
        </label>
        <div style="margin-bottom: 1.5rem">
          <label class="form-label" for="cycle-interval">Seconds between rotations</label>
          <input
            id="cycle-interval"
            class="form-control"
            type="number"
            min="1"
            step="1"
            v-model.number="cycleForm.interval_seconds"
            :disabled="!cycleForm.enabled"
            style="max-width: 140px"
          />
        </div>
        <div class="d-flex gap-sm" style="justify-content: flex-end">
          <button class="btn btn-secondary" @click="showCycleModal = false">Cancel</button>
          <button class="btn btn-primary" :disabled="commanding" @click="saveCycleConfig">Save</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { useApi } from '../composables/useApi'
import { useToastStore } from '../stores/toast'
import { useFeatureFlagsStore } from '../stores/featureFlags'
import { isCommandFresh } from '../composables/usePendingCommand'
import { API_URL } from '../config'
import UrlTypeahead from '../urls/UrlTypeahead.vue'

const { apiFetch } = useApi()
const toast = useToastStore()
const featureFlags = useFeatureFlagsStore()
const route = useRoute()

const kiosk = ref(null)
const loading = ref(true)
const commanding = ref(false)

// Event-log rows whose error detail is currently expanded.
const expandedRows = ref(new Set())
function toggleRow(id) {
  const next = new Set(expandedRows.value)
  next.has(id) ? next.delete(id) : next.add(id)
  expandedRows.value = next
}
const urlInput = ref('')
const showRebootModal = ref(false)
const showUpdateModal = ref(false)
// Base agent version the server expects (from GET /_version); null on a dev server.
const latestAgentVersion = ref(null)

const liveStatus = ref(null)
const liveUrl = ref(null)
const liveInput = ref(null)
const liveDisplayOn = ref(null)
const liveBrightness = ref(80)  // initialized from the last commanded value (meta.brightness)
const liveUptimeSeconds = ref(null)
const liveUptimeReportedAt = ref(null)
const liveTabs = ref([])
const newTabUrl = ref('')
// Optimistic placeholders for tabs the user just opened, shown immediately while
// we wait for the agent to report the real tab (with title/active/age) back.
const pendingTabs = ref([])
// Id of a tab the user just hit Focus on — shown as active (with a spinner) until
// the agent confirms it's the on-screen tab.
const pendingFocusTabId = ref(null)
let pendingFocusAt = 0
// Map of tabId -> click time (ms) for tabs the user just hit Refresh on — shown as
// "refreshing…" until the agent reports a last-reload newer than the click.
const pendingRefreshTabs = ref({})
// Map of tabId -> click time (ms) for tabs the user just closed — kept hidden even if
// a stale heartbeat snapshot still lists them, until the agent confirms removal. Stops
// the close→reappear→close flicker.
const pendingCloseTabs = ref({})
let sse = null
let logPollInterval = null
let countdownInterval = null
let pollInterval = null
let tabPollInterval = null
let pendingTabSeq = 0
const PENDING_TAB_TIMEOUT_MS = 30000
// Wall-clock (ms) of the last tab snapshot, so "refreshed Xs ago" ticks up
// smoothly between the agent's ~30s updates instead of jumping.
const tabsUpdatedAt = ref(Date.now())

const commandLog = ref([])
const savedUrls = ref([])
const availablePlaylists = ref([])
const attachedPlaylist = ref(null)
const attachedPlaylistItems = ref([])
const selectedPlaylistId = ref('')
const showChangePlaylist = ref(false)
const livePlaylistState = ref(null)
const liveTabCycleState = ref(null)
const showCycleModal = ref(false)
// Editable copy of the node's tab_cycle config, bound to the modal inputs.
const cycleForm = ref({ enabled: false, interval_seconds: 15 })
// URL of the tab row currently being dragged, for the reorder interaction.
const dragTabUrl = ref(null)
const countdownTick = ref(0)

// A command the agent hasn't acknowledged yet (status 'pending'). The log is
// sorted newest-first, so this is the most recent outstanding command. We block
// new commands while one is pending so they don't back up the agent's queue —
// but only briefly (COMMAND_BLOCK_WINDOW_MS via isCommandFresh), so an offline or
// slow node can't lock the controls until the server ages it to "no_response"
// (2 min). countdownTick (1s) drives the time-based re-evaluation.
const pendingCommand = computed(() => commandLog.value.find(e => e.status === 'pending') || null)
const commandsBlocked = computed(() => {
  if (commanding.value) return true
  void countdownTick.value
  return pendingCommand.value !== null && isCommandFresh(pendingCommand.value.sent_at, Date.now())
})

// Surface the pause as a toast (instead of an inline banner) and clear it when the
// command resolves. Keyed by command id so re-sends re-notify.
watch(() => pendingCommand.value?.id, (id) => {
  if (id && commandsBlocked.value) {
    toast.add(`Commands paused — waiting for "${pendingCommand.value.command}" to finish`, 'warning')
  }
})

const ALL_INPUTS = [
  { value: 'dp1',   defaultLabel: 'DP 1' },
  { value: 'dp2',   defaultLabel: 'DP 2' },
  { value: 'hdmi1', defaultLabel: 'HDMI 1' },
  { value: 'hdmi2', defaultLabel: 'HDMI 2' },
]

const INPUTS = computed(() => {
  const labels = kiosk.value?.meta?.input_labels ?? {}
  const hidden = new Set(kiosk.value?.meta?.hidden_inputs ?? [])
  return ALL_INPUTS
    .filter(i => !hidden.has(i.value))
    .map(i => ({ value: i.value, label: labels[i.value] ?? i.defaultLabel }))
})

const hiddenControls = computed(() => new Set(kiosk.value?.meta?.hidden_controls ?? []))

const filePermissionErrors = computed(() => {
  const errors = kiosk.value?.meta?.file_permission_errors
  return Array.isArray(errors) ? [...errors].reverse() : []
})

const visibleControls = computed(() => {
  if (!kiosk.value?.features?.length) return []
  return kiosk.value.features.filter(f => !hiddenControls.value.has(f))
})

const kioskId = computed(() => route.params.id)

const playlistActiveIdx = computed(() => livePlaylistState.value?.idx ?? null)
const playlistPlaying = computed(() => livePlaylistState.value != null)

// Tab cycling: live running state comes over the heartbeat (tab_cycle_state);
// the enable flag + interval are persisted per-node in meta.tab_cycle.
const tabCyclePlaying = computed(() => liveTabCycleState.value != null)
const tabCycleConfig = computed(() => kiosk.value?.meta?.tab_cycle ?? null)
const tabCycleEnabled = computed(() => !!tabCycleConfig.value?.enabled)
const tabOrder = computed(() => kiosk.value?.meta?.tab_order ?? [])

// Rough full-loop estimate: interval × number of open tabs. Prefer the interval
// the cycle is actually running with, else the configured one.
const cycleTabCount = computed(() => liveTabs.value.length)
const cycleIntervalSeconds = computed(() =>
  Number(liveTabCycleState.value?.interval_seconds ?? tabCycleConfig.value?.interval_seconds) || 15)
const fullCycleSeconds = computed(() => cycleIntervalSeconds.value * Math.max(1, cycleTabCount.value))

// Best-guess live uptime: the value the node last reported plus the time elapsed
// since. Only trustworthy while the node is online (regular heartbeats) — if it
// stopped checking in we can't assume it stayed up (it may have rebooted), so we
// show "Unknown". countdownTick drives the once-a-second re-evaluation.
const uptimeDisplay = computed(() => {
  void countdownTick.value
  if (liveStatus.value !== 'online') return 'Unknown'
  if (liveUptimeSeconds.value == null || !liveUptimeReportedAt.value) return 'Unknown'
  const elapsed = (Date.now() - new Date(liveUptimeReportedAt.value).getTime()) / 1000
  return fmtUptime(liveUptimeSeconds.value + Math.max(0, elapsed))
})

function fmtUptime(seconds) {
  const s = Math.floor(seconds)
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (d > 0) return `${d}d ${h}h ${m}m`
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m`
  return `${s}s`
}

const playlistCountdown = computed(() => {
  // countdownTick drives re-evaluation every second
  void countdownTick.value
  const state = livePlaylistState.value
  if (!state || state.started_at == null || playlistActiveIdx.value === null) return null
  const item = attachedPlaylistItems.value[playlistActiveIdx.value]
  if (!item) return null
  const elapsed = (Date.now() - new Date(state.started_at).getTime()) / 1000
  return Math.max(0, Math.ceil(item.duration_seconds - elapsed))
})

// Lightweight live refresh — fallback in case the SSE stream drops, so the panel
// keeps updating on a regular cadence without a full reload.
async function refreshLive() {
  try {
    const k = await apiFetch(`/kiosks/${kioskId.value}`)
    liveStatus.value = k.status
    liveUrl.value = k.current_url
    liveInput.value = k.current_input || null
    liveDisplayOn.value = k.display_on ?? null
    liveUptimeSeconds.value = k.uptime_seconds ?? null
    liveUptimeReportedAt.value = k.uptime_reported_at ?? null
    liveTabs.value = k.browser_tabs || []
    tabsUpdatedAt.value = Date.now()
    livePlaylistState.value = k.playlist_state ?? null
    liveTabCycleState.value = k.tab_cycle_state ?? null
  } catch {
    // transient — SSE and the next poll will catch up
  }
}

async function load() {
  try {
    const [k, playlists, urlList] = await Promise.all([
      apiFetch(`/kiosks/${kioskId.value}`),
      apiFetch('/playlists'),
      apiFetch('/saved-urls').catch(() => []),
    ])
    savedUrls.value = urlList
    kiosk.value = k
    liveStatus.value = k.status
    liveUrl.value = k.current_url
    liveInput.value = k.current_input || null
    liveDisplayOn.value = k.display_on ?? null
    liveBrightness.value = k.meta?.brightness ?? 80
    liveUptimeSeconds.value = k.uptime_seconds ?? null
    liveUptimeReportedAt.value = k.uptime_reported_at ?? null
    liveTabs.value = k.browser_tabs || []
    tabsUpdatedAt.value = Date.now()
    livePlaylistState.value = k.playlist_state ?? null
    liveTabCycleState.value = k.tab_cycle_state ?? null
    availablePlaylists.value = playlists
    attachedPlaylist.value = k.playlist_id
      ? playlists.find(p => p.id === k.playlist_id) ?? null
      : null
    if (k.playlist_id) {
      try {
        const detail = await apiFetch(`/playlists/${k.playlist_id}`)
        attachedPlaylistItems.value = detail.items ?? []
      } catch {
        attachedPlaylistItems.value = []
      }
    } else {
      attachedPlaylistItems.value = []
    }
  } catch {
    toast.add('Failed to load kiosk', 'error')
  } finally {
    loading.value = false
  }
  // Best-effort: learn the version the server expects so we can flag an outdated
  // agent. Non-fatal — a missing/dev value just means "don't flag".
  try {
    const v = await apiFetch('/_version')
    latestAgentVersion.value = v?.agent_version ?? null
  } catch {
    latestAgentVersion.value = null
  }
}

async function attachPlaylist() {
  if (!selectedPlaylistId.value) return
  commanding.value = true
  try {
    await apiFetch(`/kiosks/${kioskId.value}/playlist`, {
      method: 'PUT',
      body: JSON.stringify({ playlist_id: selectedPlaylistId.value }),
    })
    attachedPlaylist.value = availablePlaylists.value.find(p => p.id === selectedPlaylistId.value) ?? null
    try {
      const detail = await apiFetch(`/playlists/${selectedPlaylistId.value}`)
      attachedPlaylistItems.value = detail.items ?? []
    } catch {
      attachedPlaylistItems.value = []
    }
    selectedPlaylistId.value = ''
    showChangePlaylist.value = false
    toast.add('Playlist attached', 'success')
  } catch {
    toast.add('Failed to attach playlist', 'error')
  } finally {
    commanding.value = false
  }
}

async function detachPlaylist() {
  commanding.value = true
  try {
    await apiFetch(`/kiosks/${kioskId.value}/playlist`, { method: 'DELETE' })
    attachedPlaylist.value = null
    attachedPlaylistItems.value = []
    showChangePlaylist.value = false
    toast.add('Playlist detached', 'success')
  } catch {
    toast.add('Failed to detach playlist', 'error')
  } finally {
    commanding.value = false
  }
}

async function playPlaylist() {
  commanding.value = true
  try {
    await apiFetch(`/kiosks/${kioskId.value}/playlist/play`, { method: 'POST' })
    toast.add('Playlist started', 'success')
    await loadCommandLog()
  } catch {
    toast.add('Failed to start playlist', 'error')
  } finally {
    commanding.value = false
  }
}

async function stopPlaylist() {
  commanding.value = true
  try {
    await apiFetch(`/kiosks/${kioskId.value}/playlist/stop`, { method: 'POST' })
    toast.add('Playlist stopped', 'success')
    await loadCommandLog()
  } catch {
    toast.add('Failed to stop playlist', 'error')
  } finally {
    commanding.value = false
  }
}

async function gotoPlaylistItem(index) {
  commanding.value = true
  try {
    await apiFetch(`/kiosks/${kioskId.value}/playlist/goto`, {
      method: 'POST',
      body: JSON.stringify({ index }),
    })
    toast.add(`Jumped to item ${index + 1}`, 'success')
    await loadCommandLog()
  } catch {
    toast.add('Failed to jump to item', 'error')
  } finally {
    commanding.value = false
  }
}

async function loadCommandLog() {
  try {
    commandLog.value = await apiFetch(`/kiosks/${kioskId.value}/command-log`)
  } catch {
    // non-fatal — log section just stays empty
  }
}

async function connectSSE() {
  // EventSource can't send an Authorization header, so we exchange our bearer
  // token for a short-lived single-use ticket (kept out of access logs) and
  // pass that in the query string instead.
  const base = `${API_URL}/kiosks/${kioskId.value}/sse`
  let url = base
  try {
    const { ticket } = await apiFetch(`/kiosks/${kioskId.value}/sse-ticket`, { method: 'POST' })
    if (ticket) url = `${base}?ticket=${encodeURIComponent(ticket)}`
  } catch {
    return  // not authorized / fetch failed — skip the stream rather than leak a token
  }
  sse = new EventSource(url)
  sse.addEventListener('status', e => {
    try {
      const data = JSON.parse(e.data)
      liveStatus.value = data.online ? 'online' : 'offline'
      liveUrl.value = data.current_url || null
      if (data.browser_tabs != null) { liveTabs.value = data.browser_tabs; tabsUpdatedAt.value = Date.now() }
      if ('playlist_state' in data) livePlaylistState.value = data.playlist_state
      if ('tab_cycle_state' in data) liveTabCycleState.value = data.tab_cycle_state
      // Reflect a new agent version live (e.g. after an update) so the version and
      // the "update available" badge refresh without a page reload.
      if ('agent_version' in data && kiosk.value) kiosk.value.agent_version = data.agent_version
      if (kiosk.value) kiosk.value.last_seen = new Date().toISOString()
    } catch {}
  })
}

async function confirmReboot() {
  showRebootModal.value = false
  await sendCommand('reboot')
}

// Compare two dotted version strings numerically. Returns true when `a` is strictly
// older than `b`. Falls back to plain inequality if either doesn't parse cleanly.
function versionIsOlder(a, b) {
  const parse = s => String(s).split('.').map(n => parseInt(n, 10))
  const pa = parse(a), pb = parse(b)
  if (pa.some(Number.isNaN) || pb.some(Number.isNaN)) return a !== b
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const x = pa[i] ?? 0, y = pb[i] ?? 0
    if (x !== y) return x < y
  }
  return false
}

// Outdated only when we know both the node's version and the server's expected
// version, and the node's is older. (Dev servers report null → never flagged.)
const agentOutdated = computed(() =>
  !!kiosk.value?.agent_version &&
  !!latestAgentVersion.value &&
  versionIsOlder(kiosk.value.agent_version, latestAgentVersion.value))

async function confirmUpdateAgent() {
  showUpdateModal.value = false
  if (blockedByPending()) return
  commanding.value = true
  try {
    await apiFetch(`/kiosks/${kioskId.value}/agent/update`, { method: 'POST' })
    toast.add('Update started — the node will pull the latest code and restart', 'success')
    await loadCommandLog()
  } catch {
    toast.add('Failed to start update', 'error')
  } finally {
    commanding.value = false
  }
}

// Belt-and-suspenders for the disabled buttons: forms can still submit via Enter,
// so refuse to queue a new command while one is pending.
function blockedByPending() {
  if (pendingCommand.value) {
    toast.add(`Wait for "${pendingCommand.value.command}" to finish first`, 'info')
    return true
  }
  return false
}

async function sendCommand(command, url = null) {
  if (blockedByPending()) return
  commanding.value = true
  try {
    const body = { command }
    if (url) body.url = url
    await apiFetch(`/kiosks/${kioskId.value}/command`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
    toast.add(`${command} sent`, 'success')
    await loadCommandLog()
  } catch {
    toast.add('Failed to send command', 'error')
  } finally {
    commanding.value = false
  }
}

async function sendDisplayCommand(command, expectedState) {
  if (blockedByPending()) return
  commanding.value = true
  try {
    await apiFetch(`/kiosks/${kioskId.value}/command`, {
      method: 'POST',
      body: JSON.stringify({ command }),
    })
    liveDisplayOn.value = expectedState
    toast.add(`Display ${expectedState ? 'on' : 'off'}`, 'success')
  } catch {
    toast.add('Failed to send display command', 'error')
  } finally {
    commanding.value = false
  }
}

async function sendInput(input) {
  if (blockedByPending()) return
  commanding.value = true
  try {
    await apiFetch(`/kiosks/${kioskId.value}/input`, {
      method: 'POST',
      body: JSON.stringify({ input }),
    })
    liveInput.value = input
    toast.add(`Input switched to ${input}`, 'success')
  } catch {
    toast.add('Failed to switch input', 'error')
  } finally {
    commanding.value = false
  }
}

async function sendBrightness(value) {
  if (blockedByPending()) return
  commanding.value = true
  try {
    await apiFetch(`/kiosks/${kioskId.value}/brightness`, {
      method: 'PUT',
      body: JSON.stringify({ value }),
    })
    liveBrightness.value = value
    toast.add(`Brightness set to ${value}%`, 'success')
  } catch {
    toast.add('Failed to set brightness', 'error')
  } finally {
    commanding.value = false
  }
}

async function sendNav() {
  if (blockedByPending()) return
  try {
    await apiFetch(`/kiosks/${kioskId.value}/navigate`, {
      method: 'POST',
      body: JSON.stringify({ url: urlInput.value }),
    })
    livePlaylistState.value = null  // navigating stops the playlist on the node
    liveTabCycleState.value = null  // …and the tab cycle
    toast.add('URL sent — playlist stopped', 'success')
    urlInput.value = ''
    await loadCommandLog()
  } catch {
    toast.add('Failed to send URL', 'error')
  }
}


async function openNewTab() {
  if (blockedByPending()) return
  const url = newTabUrl.value
  commanding.value = true
  try {
    await apiFetch(`/kiosks/${kioskId.value}/browsers`, {
      method: 'POST',
      body: JSON.stringify({ url }),
    })
    // Show the tab right away; the fast poll fills in title/active/age once the
    // agent reports it back, then the placeholder is replaced by the real row.
    addPendingTab(url)
    toast.add('Tab opened', 'success')
    newTabUrl.value = ''
  } catch {
    toast.add('Failed to open tab', 'error')
  } finally {
    commanding.value = false
  }
}

async function closeTab(tabId) {
  commanding.value = true
  // Closing the last tab doesn't remove it — the agent navigates it to the default
  // page instead — so only optimistically hide when other tabs remain. Otherwise the
  // single tab would vanish and pop back with the default URL.
  const isLastTab = liveTabs.value.length <= 1
  if (!isLastTab) markPendingClose(tabId)
  try {
    await apiFetch(`/kiosks/${kioskId.value}/browsers/${tabId}`, { method: 'DELETE' })
    toast.add('Tab closed', 'success')
  } catch {
    clearPendingClose(tabId)  // un-hide on failure
    toast.add('Failed to close tab', 'error')
  } finally {
    commanding.value = false
  }
}

async function activateTab(tabId) {
  commanding.value = true
  try {
    await apiFetch(`/kiosks/${kioskId.value}/browsers/${tabId}/activate`, { method: 'POST' })
    // Show this tab as on-screen right away; the fast poll confirms once the agent
    // reports it active, then the optimistic override is dropped.
    markPendingFocus(tabId)
    livePlaylistState.value = null  // focusing a tab stops the playlist on the node
    liveTabCycleState.value = null  // …and the tab cycle
    toast.add('Tab focused', 'success')
  } catch {
    toast.add('Failed to focus tab', 'error')
  } finally {
    commanding.value = false
  }
}

async function refreshTab(tabId) {
  if (blockedByPending()) return
  commanding.value = true
  try {
    await apiFetch(`/kiosks/${kioskId.value}/browsers/${tabId}/refresh`, { method: 'POST' })
    // Show the tab as "refreshing…" right away; the fast poll clears it once the
    // agent reports the tab reloaded (its age resets).
    markPendingRefresh(tabId)
    toast.add('Tab refresh sent', 'success')
  } catch {
    toast.add('Failed to refresh tab', 'error')
  } finally {
    commanding.value = false
  }
}

// --- Tab cycling ---

function openCycleModal() {
  // Seed the form from the persisted config so the modal reflects current settings.
  const cfg = tabCycleConfig.value
  cycleForm.value = {
    enabled: !!cfg?.enabled,
    interval_seconds: Number(cfg?.interval_seconds) || 15,
  }
  showCycleModal.value = true
}

async function saveCycleConfig() {
  const interval = Math.max(1, Math.round(Number(cycleForm.value.interval_seconds) || 15))
  const value = { enabled: !!cycleForm.value.enabled, interval_seconds: interval }
  commanding.value = true
  try {
    await apiFetch(`/kiosks/${kioskId.value}/meta/tab_cycle`, {
      method: 'PUT',
      body: JSON.stringify({ key: 'tab_cycle', value }),
    })
    if (kiosk.value) kiosk.value.meta = { ...kiosk.value.meta, tab_cycle: value }
    showCycleModal.value = false
    // If cycling is disabled, make sure it isn't left running; if it's running and
    // the interval changed, restart so the new cadence takes effect immediately.
    if (!value.enabled && tabCyclePlaying.value) {
      await stopTabCycle()
    } else if (value.enabled && tabCyclePlaying.value) {
      await startTabCycle()
    }
    toast.add('Cycle settings saved', 'success')
  } catch {
    toast.add('Failed to save cycle settings', 'error')
  } finally {
    commanding.value = false
  }
}

async function startTabCycle() {
  if (blockedByPending()) return
  commanding.value = true
  // Flip the button to the running state right away (don't wait for the next
  // heartbeat to report tab_cycle_state); the heartbeat then replaces this with
  // the agent's real state. Reverted if the request fails.
  const interval = Number(tabCycleConfig.value?.interval_seconds) || 15
  liveTabCycleState.value = { interval_seconds: interval, current_tab_id: null, started_at: new Date().toISOString() }
  try {
    await apiFetch(`/kiosks/${kioskId.value}/tabs/cycle/start`, { method: 'POST' })
    toast.add('Tab cycling started', 'success')
    await loadCommandLog()
  } catch {
    liveTabCycleState.value = null
    toast.add('Failed to start cycling', 'error')
  } finally {
    commanding.value = false
  }
}

// Compact "full loop" duration, e.g. 45s, 1m 30s, 2m.
function fmtCycleEstimate(seconds) {
  const s = Math.round(seconds)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const rem = s % 60
  return rem ? `${m}m ${rem}s` : `${m}m`
}

async function stopTabCycle() {
  if (blockedByPending()) return
  commanding.value = true
  try {
    await apiFetch(`/kiosks/${kioskId.value}/tabs/cycle/stop`, { method: 'POST' })
    liveTabCycleState.value = null  // clear optimistically; heartbeat confirms
    toast.add('Tab cycling stopped', 'success')
    await loadCommandLog()
  } catch {
    toast.add('Failed to stop cycling', 'error')
  } finally {
    commanding.value = false
  }
}

// --- Tab drag-reorder ---
// CDP can't reorder Chromium's real tab strip, so this persists a dashboard-side
// order (by URL) in meta.tab_order. It drives the listed order and the cycle
// sequence. Tabs whose URL isn't in the list fall to the end (see orderTabs).

function onTabDragStart(tab) {
  dragTabUrl.value = tab.url
}

function onTabDrop(targetTab) {
  const fromUrl = dragTabUrl.value
  dragTabUrl.value = null
  if (!fromUrl || targetTab.pending || fromUrl === targetTab.url) return
  // Reorder the URLs of the currently-displayed real tabs, then persist.
  const urls = displayTabs.value.filter(t => !t.pending).map(t => t.url)
  const from = urls.indexOf(fromUrl)
  const to = urls.indexOf(targetTab.url)
  if (from < 0 || to < 0) return
  const [moved] = urls.splice(from, 1)
  urls.splice(to, 0, moved)
  saveTabOrder(urls)
}

async function saveTabOrder(urls) {
  // Optimistically apply so the list reorders instantly.
  if (kiosk.value) kiosk.value.meta = { ...kiosk.value.meta, tab_order: urls }
  try {
    await apiFetch(`/kiosks/${kioskId.value}/meta/tab_order`, {
      method: 'PUT',
      body: JSON.stringify({ key: 'tab_order', value: urls }),
    })
    // If a cycle is running, restart it so it picks up the new order.
    if (tabCyclePlaying.value) await startTabCycle()
  } catch {
    toast.add('Failed to save tab order', 'error')
  }
}

function savedUrlFor(tabUrl) {
  if (!tabUrl) return null
  const norm = normUrl(tabUrl)
  return savedUrls.value.find(u => normUrl(u.url) === norm) ?? null
}

function normUrl(u) {
  return (u || '').replace(/\/$/, '')
}

// Color the HTTP status the page received: 2xx green, 4xx/5xx red, anything else
// (3xx, etc.) neutral. Returned as an inline style for the badge pill.
function statusBadgeStyle(code) {
  const base = 'font-weight: 600; font-size: 0.65rem; line-height: 1; padding: 0.15rem 0.35rem; border: 1px solid; border-radius: var(--radius-sm); flex-shrink: 0;'
  if (code >= 200 && code < 300) return base + ' color: var(--success); border-color: color-mix(in srgb, var(--success) 45%, transparent)'
  if (code >= 400 && code < 600) return base + ' color: var(--danger); border-color: color-mix(in srgb, var(--danger) 45%, transparent)'
  return base + ' color: var(--text-muted); border-color: var(--border)'
}

// Order live tabs by the operator's saved order (meta.tab_order, by URL). Tabs
// whose URL isn't in the list keep their reported order at the end — Array.sort is
// stable, so equal-rank tabs aren't reshuffled.
function orderTabs(tabs) {
  const order = tabOrder.value
  if (!order || !order.length) return tabs
  const rank = new Map(order.map((u, i) => [normUrl(u), i]))
  const rankOf = t => (rank.has(normUrl(t.url)) ? rank.get(normUrl(t.url)) : order.length)
  return [...tabs].sort((a, b) => rankOf(a) - rankOf(b))
}

// Real tabs from the agent (in saved order), plus any optimistic pending tabs whose
// URL the agent hasn't reported yet. Once a pending tab's URL shows up in liveTabs the
// watcher below drops the placeholder, so the real (detailed) row takes its place.
const displayTabs = computed(() => {
  // Hide tabs the user just closed until the agent's snapshot drops them (the
  // watcher clears the marker), so a stale heartbeat can't flicker them back.
  const closing = pendingCloseTabs.value
  const live = liveTabs.value.filter(t => !closing[t.id])
  const liveUrls = new Set(live.map(t => normUrl(t.url)))
  const unresolved = pendingTabs.value.filter(t => !liveUrls.has(normUrl(t.url)))
  return [...orderTabs(live), ...unresolved]
})

// Effective on-screen state: while a Focus is pending, optimistically treat the
// clicked tab as the active one (only one tab can be active) until the agent
// confirms; otherwise trust the reported flag.
function isTabActive(tab) {
  if (pendingFocusTabId.value != null) return tab.id === pendingFocusTabId.value
  return !!tab.active
}

function hasPendingTabWork() {
  return pendingTabs.value.length > 0
    || pendingFocusTabId.value != null
    || Object.keys(pendingRefreshTabs.value).length > 0
    || Object.keys(pendingCloseTabs.value).length > 0
}

// A refresh is confirmed once the agent reports this tab's last reload as newer
// than the click. age_seconds is a node-measured duration (skew-free); subtracting
// it from the snapshot's wall-clock gives the absolute reload time to compare.
function refreshConfirmed(tab, clickTime) {
  if (tab.age_seconds != null) {
    return tabsUpdatedAt.value - tab.age_seconds * 1000 >= clickTime - 1500
  }
  // No age info — accept the first fresh snapshot taken after the click.
  return tabsUpdatedAt.value > clickTime
}

// Whenever fresh tab data arrives (SSE or poll), retire anything the agent has now
// confirmed — placeholders whose URL showed up, a focus whose tab is now active, and
// refreshes whose tab reloaded — then stop the fast poll once nothing is pending.
watch(liveTabs, (tabs) => {
  if (pendingTabs.value.length) {
    const liveUrls = new Set(tabs.map(t => normUrl(t.url)))
    pendingTabs.value = pendingTabs.value.filter(t => !liveUrls.has(normUrl(t.url)))
  }
  if (pendingFocusTabId.value != null) {
    const t = tabs.find(t => t.id === pendingFocusTabId.value)
    if (t && t.active) pendingFocusTabId.value = null
  }
  const refreshIds = Object.keys(pendingRefreshTabs.value)
  if (refreshIds.length) {
    const next = { ...pendingRefreshTabs.value }
    let changed = false
    for (const tab of tabs) {
      const ct = next[tab.id]
      if (ct != null && refreshConfirmed(tab, ct)) { delete next[tab.id]; changed = true }
    }
    if (changed) pendingRefreshTabs.value = next
  }
  const closeIds = Object.keys(pendingCloseTabs.value)
  if (closeIds.length) {
    const liveIds = new Set(tabs.map(t => t.id))
    const next = { ...pendingCloseTabs.value }
    let changed = false
    for (const id of closeIds) {
      if (!liveIds.has(id)) { delete next[id]; changed = true }  // agent confirmed it's gone
    }
    if (changed) pendingCloseTabs.value = next
  }
  if (!hasPendingTabWork()) stopTabPolling()
})

function addPendingTab(url) {
  pendingTabs.value.push({ id: `pending-${++pendingTabSeq}`, url, pending: true, createdAt: Date.now() })
  startTabPolling()
}

function markPendingFocus(tabId) {
  pendingFocusTabId.value = tabId
  pendingFocusAt = Date.now()
  startTabPolling()
}

function markPendingRefresh(tabId) {
  pendingRefreshTabs.value = { ...pendingRefreshTabs.value, [tabId]: Date.now() }
  startTabPolling()
}

function markPendingClose(tabId) {
  pendingCloseTabs.value = { ...pendingCloseTabs.value, [tabId]: Date.now() }
  startTabPolling()
}

function clearPendingClose(tabId) {
  if (pendingCloseTabs.value[tabId] == null) return
  const next = { ...pendingCloseTabs.value }
  delete next[tabId]
  pendingCloseTabs.value = next
}

// While tab work is pending, poll the API faster than the 15s background cadence so
// placeholders fill in (or time out) quickly. refreshLive() updates liveTabs, which
// the watcher above reconciles against pendingTabs / pendingFocusTabId.
function startTabPolling() {
  if (tabPollInterval) return
  tabPollInterval = setInterval(async () => {
    await refreshLive()
    const now = Date.now()
    const cutoff = now - PENDING_TAB_TIMEOUT_MS
    const timedOut = pendingTabs.value.filter(t => t.createdAt < cutoff)
    if (timedOut.length) {
      pendingTabs.value = pendingTabs.value.filter(t => t.createdAt >= cutoff)
      toast.add('Tab is taking longer than expected — the node may be offline', 'warning')
    }
    if (pendingFocusTabId.value != null && now - pendingFocusAt > PENDING_TAB_TIMEOUT_MS) {
      pendingFocusTabId.value = null
      toast.add('Focus is taking longer than expected — the node may be offline', 'warning')
    }
    const staleRefresh = Object.entries(pendingRefreshTabs.value).filter(([, ct]) => now - ct > PENDING_TAB_TIMEOUT_MS)
    if (staleRefresh.length) {
      const next = { ...pendingRefreshTabs.value }
      for (const [id] of staleRefresh) delete next[id]
      pendingRefreshTabs.value = next
      toast.add('Refresh is taking longer than expected — the node may be offline', 'warning')
    }
    const staleClose = Object.entries(pendingCloseTabs.value).filter(([, ct]) => now - ct > PENDING_TAB_TIMEOUT_MS)
    if (staleClose.length) {
      const next = { ...pendingCloseTabs.value }
      for (const [id] of staleClose) delete next[id]
      pendingCloseTabs.value = next
      toast.add('Close is taking longer than expected — the node may be offline', 'warning')
    }
    if (!hasPendingTabWork()) stopTabPolling()
  }, 2000)
}

function stopTabPolling() {
  if (tabPollInterval) { clearInterval(tabPollInterval); tabPollInterval = null }
}

function truncateUrl(url) {
  if (!url) return ''
  try {
    const u = new URL(url)
    const withoutProto = u.host + u.pathname + u.search
    if (withoutProto.length <= 60) return withoutProto
    const parts = u.pathname.split('/').filter(Boolean)
    if (parts.length === 0) return u.hostname
    // Try last two segments
    const tail2 = parts.slice(-2).join('/')
    if ((u.hostname + '/…/' + tail2).length <= 60) return u.hostname + '/…/' + tail2
    // Fall back to last segment only
    const last = parts[parts.length - 1]
    if ((u.hostname + '/…/' + last).length <= 60) return u.hostname + '/…/' + last
    // Truncate the last segment
    return u.hostname + '/…/' + last.slice(0, 20) + '…'
  } catch {
    return url.length > 60 ? url.slice(0, 57) + '…' : url
  }
}

function fmtAge(seconds) {
  const s = Math.max(0, Math.round(seconds))
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`
}

// Age at the last snapshot plus the wall-clock elapsed since, so it ticks every
// second. countdownTick drives re-evaluation.
function tabAge(tab) {
  void countdownTick.value
  if (tab.age_seconds == null) return null
  return tab.age_seconds + (Date.now() - tabsUpdatedAt.value) / 1000
}

function formatDate(ts) {
  return new Date(ts).toLocaleString()
}

function formatLastSeen(ts) {
  if (!ts) return 'never'
  return new Date(ts).toLocaleString()
}

onMounted(() => {
  load().then(connectSSE)
  loadCommandLog()
  logPollInterval = setInterval(loadCommandLog, 5000)
  countdownInterval = setInterval(() => { countdownTick.value++ }, 1000)
  pollInterval = setInterval(refreshLive, 15000)  // SSE fallback / regular refresh
})

onUnmounted(() => {
  if (sse) sse.close()
  clearInterval(logPollInterval)
  clearInterval(countdownInterval)
  clearInterval(pollInterval)
  stopTabPolling()
})
</script>

<style scoped>
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-box {
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1.75rem;
  width: 100%;
  max-width: 380px;
}

.modal-title {
  font-size: 1.1rem;
  font-weight: 600;
  margin: 0;
}

.row-expandable {
  cursor: pointer;
}
.row-expandable:hover td {
  background: rgba(255, 255, 255, 0.03);
}

.result-cell {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
}
.result-ok {
  color: var(--success);
  font-size: 0.85rem;
  font-weight: 600;
}
.result-fail {
  color: var(--danger);
  font-size: 0.8rem;
}
.expand-caret {
  font-size: 0.7rem;
  color: var(--text-muted);
}

.msg-detail-row td {
  padding: 0;
}
.msg-detail {
  margin: 0;
  padding: 0.6rem 0.85rem;
  background: rgba(255, 255, 255, 0.03);
  border-left: 2px solid var(--border);
  color: var(--text-muted);
  font-size: 0.75rem;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.msg-detail.is-error {
  background: rgba(239, 68, 68, 0.08);
  border-left-color: var(--danger);
  color: var(--danger);
}
</style>
