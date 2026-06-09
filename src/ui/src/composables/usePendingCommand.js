import { ref, computed, onUnmounted } from 'vue'
import { useApi } from './useApi'

/**
 * Tracks whether the kiosk has a command the agent hasn't acknowledged yet.
 *
 * The agent processes commands serially, so sending a new one while a previous
 * command is still "pending" risks backing up its queue. Components use this to
 * disable command buttons until the last command resolves (ok / failed) or times
 * out to "no_response" (so a missed command never locks the UI permanently).
 *
 * @param kioskId  a ref, getter, or plain id
 */
export function usePendingCommand(kioskId, { intervalMs = 4000 } = {}) {
  const { apiFetch } = useApi()
  const log = ref([])
  let timer = null

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
  const blocked = computed(() => pendingCommand.value !== null)

  refresh()
  timer = setInterval(refresh, intervalMs)
  onUnmounted(() => {
    if (timer) clearInterval(timer)
  })

  return { pendingCommand, blocked, refresh }
}
