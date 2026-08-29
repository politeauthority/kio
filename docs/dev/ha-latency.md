# Home Assistant ↔ kiosk latency

Working notes for the effort to make kio feel immediate from Home Assistant.
Each strategy below is tried on its own so we can tell what actually moved the
number. Update the status table as each lands; keep the measurements.

## The problem

Sending a command from HA is fast. Seeing the result in HA is not. Measured
with the code as of v0.8.2:

```
HA service call ─▶ POST /kiosks/{id}/…  ─▶ MQTT ─▶ agent acts        ~1 s
                                                                       │
agent reports state ◀─────────── next heartbeat (every 30 s) ◀─────────┘
        │
HA sees state ◀──── next coordinator poll of GET /kiosks (every 30 s)
```

Two independent 30-second clocks sit on the feedback path, so the entity
snaps back to its old state right after the call (the coordinator refreshes
immediately, but reads the stale row) and only catches up 30–60 s later.
Typical feel: 30–45 s. The dashboard has the same lag for the same reason.

Where each delay lives:

| Hop | Cadence | Where |
|---|---|---|
| Agent → API state report | heartbeat, 30 s (`heartbeat_interval_seconds`, floor 5) | `kio_agent/agent.py` `_heartbeat_loop` / `_post_heartbeat` |
| Command ack | immediate, but carries no state | `kio_agent/commands.py` `handle_command` → `_report_command` |
| API → HA | `GET /kiosks` poll, 30 s (`SCAN_INTERVAL`) | `custom_components/kio/coordinator.py` |
| API → HA after a write | one refresh right away, before the agent has acted | `KioCoordinator._command` |
| API push channel | exists: `GET /kiosks/{id}/sse` (ticket auth), fires on every heartbeat | `app/routers/sse.py`, `app/mqtt.notify_subscribers` |

Existing precedents for pushing state early: the tab cycler posts a heartbeat
after every rotation (`TabCycler(on_rotate=…)`), and `reboot` snapshots tabs
with a heartbeat before going down.

## How we measure

Same test each time, from a laptop on the LAN, against a real node:

1. `media_player.media_pause` / `media_play` on a playing kiosk from
   Developer Tools → Actions; stopwatch from the call to the entity state
   changing in Developer Tools → States. Five runs, report median and max.
2. `kio.navigate` to a saved URL; time to the `Page` select / `Current URL`
   sensor updating.
3. Sanity: watch the node's `journalctl -u kio-agent -f` to confirm the
   command itself still lands in ~1 s (we are not trying to fix that leg).

Record results under each strategy. Baseline (v0.8.2): pause/play median ~40 s,
max ~60 s; navigate similar.

## Strategies

Ordered by expected payoff per line of code. Each is its own PR so it can be
measured alone and reverted alone.

### 1. Agent pushes a heartbeat after state-changing commands — **PR #69**

Hypothesis: most of the delay is the agent sitting on new state for up to
30 s. If `handle_command` posts a heartbeat once a handler that changes
observable state succeeds, the API row is fresh within ~1 s of the action and
both HA and the dashboard only wait on their own poll.

Scope: playlist play/pause/resume/stop/goto, navigate, tab open/close/
activate/refresh, display on/off, set_input, set_brightness, tab cycle
start/stop. Not: reboot/update (already handled), sync_* / detect (no user-
visible state), reload (URL unchanged).

Cost: one extra heartbeat per command. Negligible.

Expected: HA median drops from ~40 s to ~15 s (half a poll interval);
dashboard (SSE) becomes ~1 s.

Result: _pending_

### 2. HA: refresh again a couple of seconds after a write

Hypothesis: `_command()` refreshes immediately, which is too early to see the
agent's report even with strategy 1. Schedule a second refresh ~2–3 s after
the write (keep the immediate one so a failed request still surfaces).

Depends on 1. Change is local to `coordinator.py`.

Expected, with 1: HA median ~3 s for anything triggered from HA. Changes made
elsewhere (dashboard, the kiosk itself) still wait on the poll.

Result: _pending_

### 3. HA subscribes to the API's SSE instead of polling

Hypothesis: the API already pushes on every heartbeat. A background task per
kiosk on `GET /kiosks/{id}/sse` feeding `async_set_updated_data` makes the
integration `local_push`; the 30 s poll stays as a safety net. Covers changes
that did not originate in HA.

Needs: ticket refresh (`POST /kiosks/{id}/sse-ticket`), reconnect with
backoff, one stream per kiosk (or a new "all kiosks" stream on the API —
cheaper on connections, needs an API change), lifecycle on entry unload.
Listed as Phase 3 in `src/ha-integration/PLAN.md`.

Expected, with 1: everything ~1–2 s, from any origin.

Result: _pending_

### 4. Shorter heartbeat interval

Hypothesis: lowering `heartbeat_interval_seconds` (server setting, per node)
to 10–15 s narrows the window for changes that no command triggered (someone
touching the kiosk directly).

Cost: proportional traffic and DB writes from every node; `last_seen`
offline-detection sweeper assumes 90 s. Not a lever for command latency once
1 is in. Try only if 1–3 leave a case that matters.

Result: _pending_

### 5. Optimistic state in HA

Hypothesis: flip the media player / switch / select to the requested state
on the service call (`_attr_assumed_state`) and let the next report confirm
or correct it. Feels instant; lies when the command fails.

Only worth layering on top of 1+2, and only for entities whose commands
rarely fail.

Result: _pending_

## Status

| # | Strategy | PR | Status | pause/play median | navigate median |
|---|---|---|---|---|---|
| — | baseline v0.8.2 | — | measured | ~40 s | ~40 s |
| 1 | heartbeat after commands | #69 | PR open — measure once nodes run it | | |
| 2 | delayed post-write refresh | — | | | |
| 3 | SSE push in HA | — | | | |
| 4 | shorter heartbeat | — | | | |
| 5 | optimistic state | — | | | |

## Log

- 2026-08-29 — traced the round trip, wrote this plan, started on strategy 1.
- 2026-08-29 — strategy 1 implemented: `handle_command` schedules a heartbeat 1 s after any state-changing command; the nav topic handler does the same after `navigate`. Measure after the agent update lands on a node.
