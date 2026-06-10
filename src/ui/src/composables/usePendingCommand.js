import { ref, computed, onUnmounted } from 'vue'
import { useApi } from './useApi'

// How long a still-unacknowledged command keeps the command panel disabled.
//
// The block exists ONLY to stop rapid re-sends from backing up the agent's
// serial queue — a healthy agent acks within a second or two. We deliberately do
// NOT block for the full server-side "no_response" window (2 min): a node that's
// offline, slow, or missed the message would otherwise freeze the controls for
// two minutes. After this window we let the operator act again; re-sends are
// safe because the agent tolerates them.
export const COMMAND_BLOCK_WINDOW_MS = 15000

// True while `sentAt` (ISO timestamp) is within the block window. Exported so the
// components that track the command log themselves (e.g. KioskDetail) apply the
// exact same rule. `nowMs` is passed in so the caller controls the reactive clock.
export function isCommandFresh(sentAt, nowMs) {
  if (!sentAt) return false
  const sentMs = new Date(sentAt).getTime()
  if (Number.isNaN(sentMs)) return true // can't tell age — fail safe and block
  return nowMs - sentMs < COMMAND_BLOCK_WINDOW_MS
}

/**
 * Tracks whether the kiosk has a *recent* command the agent hasn't acknowledged.
 *
 * The agent processes commands serially, so sending a new one while a previous
 * command is still "pending" risks backing up its queue. Components use this to
 * disable command buttons — but only for COMMAND_BLOCK_WINDOW_MS after the
 * command was sent, so an unresponsive node never locks the UI for long.
 *
 * @param kioskId  a ref, getter, or plain id
 */
export function usePendingCommand(kioskId, { intervalMs = 4000 } = {}) {
  const { apiFetch } = useApi()
  const log = ref([])
  const nowMs = ref(Date.now())
  let timer = null
  let clock = null

  function idOf() {
    if (typeof kioskId === 'function') return kioskId()
    return kioskId?.value ?? kioskId
  }

  async function refresh() {
    const id = idOf()
    if (!id) return
    try {
      log.value = await apiFetch(`/kiosks/${id}/command-log`)
    } catch {
      // non-fatal — leave the last known log in place
    }
  }

  // The command log is sorted newest-first, so the first pending row is the most
  // recent one still awaiting the agent.
  const pendingCommand = computed(() => log.value.find((e) => e.status === 'pending') || null)
  // Only block while that command is still fresh. `nowMs` ticks every second so
  // the block lifts on time without waiting for the next (slower) log refresh.
  const blocked = computed(() => pendingCommand.value !== null && isCommandFresh(pendingCommand.value.sent_at, nowMs.value))

  refresh()
  timer = setInterval(refresh, intervalMs)
  clock = setInterval(() => { nowMs.value = Date.now() }, 1000)
  onUnmounted(() => {
    if (timer) clearInterval(timer)
    if (clock) clearInterval(clock)
  })

  return { pendingCommand, blocked, refresh }
}
