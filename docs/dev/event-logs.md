# Event Logs

The event log is the audit trail of everything that happens to a kiosk: commands
the dashboard sends, acks the agent reports back, and system-generated events like
a node going offline. It's stored in one table — `command_logs` — and surfaced in
two places in the UI:

- **Event Log** (top nav, under Playlists) — a global, searchable view across *all*
  kiosks and the system.
- **Kiosk → Event Log** (`/kiosks/:id/log`) — the same data scoped to one kiosk.

---

## The data model

Every event is one row in `command_logs` (`src/api/app/models/command_log.py`):

| Column | Meaning |
|---|---|
| `id` | UUID. Also used as the `command_id` echoed by the agent on ack (see below). |
| `kiosk_id` | The node the event belongs to (FK, cascade delete). |
| `command` | The bare **event type** — e.g. `navigate`, `open_tab`, `set_input`. This is what the type filter lists. |
| `subject` | What the command acted on — e.g. the URL for `navigate`, the tab id for `activate_tab`. Nullable. |
| `source` | Where it originated: `dashboard`, `agent`, or `system`. |
| `sent_at` | When the dashboard/system created the record (indexed; default order is newest first). |
| `agent_success` | `True` / `False` / `NULL` — the agent's result, `NULL` until it acks. |
| `agent_message` | Free-text detail from the agent (error string, etc.). |
| `agent_at` | When the ack landed. |

> **Why `command` and `subject` are separate.** Earlier the type and its subject
> were a single string (`"navigate: https://…"`, `"activate_tab: 9F2A…"`). That
> polluted the event-type filter with one distinct value per URL/tab id. Splitting
> the subject into its own column keeps the type filter to a clean, small set of
> values. When adding a new command, **put the action in `command` and the target
> in `subject`** — never bake an id or URL into `command`.

### Derived status

The four statuses shown in the UI are **computed at read time**, not stored — see
`_command_status()` in `src/api/app/routers/kiosks.py`:

| Status | Condition |
|---|---|
| `ok` | `agent_success is True` |
| `failed` | `agent_success is False` |
| `pending` | `agent_success is NULL` and within `COMMAND_RESPONSE_TIMEOUT_SECONDS` (120s) of `sent_at` |
| `no_response` | `agent_success is NULL` and older than that window |

Computing `no_response` at read time (rather than writing it) means a late ack
still resolves a record to `ok`/`failed` normally — the agent was just slow.

---

## How events get written

```
dashboard action ──dispatch_command()──> MQTT (+command_id) ──> agent
       │                                                          │
       └── INSERT command_logs (pending)          agent runs it, POSTs /agent/command-log
                                                                  │
                          UPDATE the matching row (agent_success, message, agent_at)
```

1. **Dashboard command.** Most endpoints in `src/api/app/routers/kiosks.py` call
   `dispatch_command(session, kiosk_id, command=…, subject=…, payload=…)`. It
   inserts a `pending` row, then publishes the MQTT command tagged with that row's
   id as `command_id`.
   - `navigate` is the one exception — it publishes via `publish_nav` but inserts
     the same kind of row by hand.
2. **Agent ack.** When the agent finishes, it `POST`s to `/agent/command-log`
   (`src/api/app/routers/agent.py`) echoing the `command_id`. The handler matches
   the original row **by id** (robust to any label formatting) and fills in
   `agent_success` / `agent_message` / `agent_at`.
   - Fallback: if there's no `command_id` (agent-initiated event or an older
     agent), it matches the most recent pending row with the same `command` within
     a 5-minute window; failing that, it inserts a fresh `source="agent"` row.
3. **System events.** Written directly — e.g. `mark_offline_kiosks()` in
   `src/api/app/services/kiosk_service.py` inserts a `node offline` row with
   `source="system"` when a node misses its heartbeat. The agent also writes
   `node online` / `node rebooted` on check-in.

### Retention

A background sweeper in `src/api/app/main.py` (`_offline_sweeper`) purges
`command_logs` rows older than 7 days, hourly. There's no archival — the log is a
rolling recent-activity window, not permanent history.

---

## The search API

Two endpoints, both registered under `_dashboard_auth` in `main.py`
(`src/api/app/routers/event_logs.py`):

### `GET /event-logs`

Searches across all kiosks, newest first, joined to `kiosks` so each row carries
`kiosk_name`. Query params (all optional):

| Param | Effect |
|---|---|
| `kiosk_id` | Restrict to one kiosk. |
| `command` | Exact event-type match (the type dropdown). |
| `status` | One of `ok` / `failed` / `pending` / `no_response`. Translated to the equivalent column predicate by `_apply_status_filter`, mirroring `_command_status` so the filter and the displayed value never disagree. |
| `search` | Free-text `ILIKE` across `command`, `subject`, **and** `agent_message`. |
| `limit` / `offset` | Pagination — `limit` 1–200 (default 20). |

The total (pre-pagination) row count is returned in the **`X-Total-Count`**
response header (exposed via CORS in `main.py`), which the UI reads to build the
pager. Per-kiosk results use the analogous `GET /kiosks/{id}/command-log`.

### `GET /event-logs/commands`

Returns the distinct `command` values, sorted — used to populate the event-type
filter dropdown. Because subjects are no longer mixed into `command`, this stays a
short, stable list.

---

## The UI

| View | Component |
|---|---|
| Global Event Log | `src/ui/src/EventLog.vue` (route `/event-log`) |
| Per-kiosk Event Log | `src/ui/src/kiosks/KioskCommandLog.vue` (route `/kiosks/:id/log`) |
| Nav item | `src/ui/src/App.vue` (top nav, under Playlists) |

`EventLog.vue` loads the kiosk list (`GET /kiosks`) and the command list
(`GET /event-logs/commands`) once for its dropdowns, then re-queries `/event-logs`
whenever a filter, the debounced search box, or the page changes. Any filter change
resets to page 1. Both views render the same columns: Time, (Kiosk,) Command,
Subject, Source, Result, Agent message.

---

## Adding a new logged command

1. In the kiosks router, call
   `dispatch_command(session, kiosk_id, command="my_command", subject=<target or omit>, payload={...})`.
   Keep `command` a bare verb; put any id/URL/name in `subject`.
2. Nothing else is required for it to appear in the log or the type dropdown — the
   dropdown is derived from distinct `command` values at query time.
3. The agent should echo the `command_id` back on its `/agent/command-log` ack so
   the row resolves by id.

---

## Reference

| Layer | File |
|---|---|
| DB model | `src/api/app/models/command_log.py` |
| `subject` column migration | `src/api/alembic/versions/0021_command_log_subject.py` |
| Write path (dashboard) | `src/api/app/routers/kiosks.py` (`dispatch_command`) |
| Write path (agent ack / system) | `src/api/app/routers/agent.py`, `src/api/app/services/kiosk_service.py` |
| Search API | `src/api/app/routers/event_logs.py` (`/event-logs`) |
| Retention sweeper | `src/api/app/main.py` (`_offline_sweeper`) |
| Global UI | `src/ui/src/EventLog.vue` |
| Per-kiosk UI | `src/ui/src/kiosks/KioskCommandLog.vue` |
